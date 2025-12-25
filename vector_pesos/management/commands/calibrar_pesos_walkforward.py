from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS, TickDeriv
from vector_variables.constructor_vector import ConstructorVectorMercado, Tick
from vector_variables.normalizacion import NormalizadorOnlinePorVariable


@dataclass(frozen=True)
class ResultadoWF:
    """
    RESULTADO RESUMIDO DE UNA VENTANA WALK-FORWARD.
    """

    start_idx: int
    end_idx: int
    score_media: float
    y_media: float
    correlacion: float


def _ridge_fit(X: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    """
    AJUSTE RIDGE: (X'X + λI)^{-1} X'y

    NOTA:
    - SIN INTERCEPTO (FEATURES YA ESTÁN NORMALIZADAS ~MEDIA 0).
    """
    p = int(X.shape[1])
    XtX = X.T @ X
    A = XtX + float(lam) * np.eye(p, dtype=float)
    b = X.T @ y
    w = np.linalg.solve(A, b)
    return w.astype(float)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(float)
    b = b.astype(float)
    if a.size < 2:
        return 0.0
    sa = float(np.std(a))
    sb = float(np.std(b))
    if sa <= 0 or sb <= 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])

def _simular_binaria_por_ticks(
    *,
    scores: np.ndarray,
    precios: np.ndarray,
    horizon: int,
    umbral_compra: float,
    umbral_venta: float,
    payout_win: float,
    costo_por_trade: float,
) -> dict[str, float]:
    """
    SIMULACIÓN SIMPLE (OUT-OF-SAMPLE) PARA UNA OPCIÓN BINARIA POR TICKS.

    Supuestos:
    - Si score >= umbral_compra => "CALL" (sube).
    - Si score <= umbral_venta  => "PUT"  (baja).
    - La operación dura `horizon` ticks; mientras está abierta no abrimos otra (skip).
    - PnL por trade (en unidades de stake=1):
        +payout_win si acierta
        -1.0       si falla
      y luego restamos `costo_por_trade` (slippage/fees aproximados).

    Nota: esto NO es garantía de resultados, pero evita calibrar con métricas irreales.
    """
    n = int(scores.shape[0])
    if n <= horizon or horizon <= 0:
        return {"trades": 0.0, "winrate": 0.0, "pnl_total": 0.0, "max_drawdown": 0.0}

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    trades = 0
    wins = 0

    i = 0
    while i + horizon < n:
        s = float(scores[i])
        direccion = 0
        if s >= float(umbral_compra):
            direccion = 1
        elif s <= float(umbral_venta):
            direccion = -1

        if direccion == 0:
            i += 1
            continue

        p0 = float(precios[i])
        p1 = float(precios[i + horizon])
        mov = p1 - p0
        win = (mov > 0.0) if direccion == 1 else (mov < 0.0)
        pnl = (float(payout_win) if win else -1.0) - float(costo_por_trade)

        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        trades += 1
        if win:
            wins += 1

        # Mientras está abierta (duración por ticks), no abrimos otra.
        i += horizon

    winrate = 0.0 if trades <= 0 else (float(wins) / float(trades))
    return {
        "trades": float(trades),
        "wins": float(wins),
        "winrate": float(winrate),
        "pnl_total": float(equity),
        "max_drawdown": float(max_dd),
    }


class Command(BaseCommand):
    help = "Calibra pesos w con walk-forward (ridge) usando ticks_history de Deriv."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--symbol", type=str, default=None, help="Símbolo (ej: R_100).")
        parser.add_argument("--ticks-count", type=int, default=None, help="Cantidad de ticks a descargar.")
        parser.add_argument("--horizon-ticks", type=int, default=None, help="Horizonte (en ticks) para y.")
        parser.add_argument("--train-ticks", type=int, default=None, help="Tamaño ventana train (ticks).")
        parser.add_argument("--test-ticks", type=int, default=None, help="Tamaño ventana test (ticks).")
        parser.add_argument("--lambda-ridge", type=float, default=None, help="Regularización ridge (λ).")
        parser.add_argument("--salida", type=str, default=None, help="Ruta JSON de salida.")
        parser.add_argument("--no-escribir", action="store_true", help="Solo imprime; no escribe archivo.")
        parser.add_argument(
            "--target",
            type=str,
            default=None,
            choices=["sign", "return"],
            help="Qué aprende el ridge: 'sign' (dirección) o 'return' (retorno). Default: sign.",
        )
        parser.add_argument(
            "--payout-win",
            type=float,
            default=None,
            help="Payout por trade ganador (stake=1). Ej: 0.95. (Solo para evaluación, no trading real).",
        )
        parser.add_argument(
            "--costo-por-trade",
            type=float,
            default=None,
            help="Costo aproximado por trade (slippage/fees) en unidades de stake=1. Ej: 0.01",
        )
        parser.add_argument(
            "--min-trades-test",
            type=int,
            default=None,
            help="Mínimo de trades en el tramo de test para aceptar umbrales.",
        )
        parser.add_argument(
            "--max-trade-rate",
            type=float,
            default=None,
            help="Máxima tasa de trades permitida en OOS (trades / puntos). Ej: 0.15",
        )
        parser.add_argument(
            "--min-edge-winrate",
            type=float,
            default=None,
            help="Margen mínimo sobre el winrate de break-even para aceptar umbrales. Ej: 0.02",
        )
        parser.add_argument(
            "--max-dd-test",
            type=float,
            default=None,
            help="Máximo drawdown permitido (en unidades de stake=1 acumuladas) para aceptar umbrales.",
        )
        parser.add_argument(
            "--forzar-escritura",
            action="store_true",
            help="Permite escribir el JSON incluso si NO pasó guardrails o si el PnL OOS es <= 0 (NO recomendado).",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN001
        symbol = (options.get("symbol") or settings.DERIV_SYMBOL).strip()
        count = int(options.get("ticks_count") or settings.CALIBRADOR_TICKS_COUNT)
        horizon = int(options.get("horizon_ticks") or settings.CALIBRADOR_HORIZON_TICKS)
        train_n = int(options.get("train_ticks") or settings.CALIBRADOR_TRAIN_TICKS)
        test_n = int(options.get("test_ticks") or settings.CALIBRADOR_TEST_TICKS)
        lam = float(options.get("lambda_ridge") or settings.CALIBRADOR_LAMBDA_RIDGE)
        salida = str(options.get("salida") or settings.PESOS_ARCHIVO)
        no_escribir = bool(options.get("no_escribir"))
        payout_win = float(options.get("payout_win") or getattr(settings, "CALIBRADOR_PAYOUT_WIN", 0.95))
        costo_por_trade = float(options.get("costo_por_trade") or getattr(settings, "CALIBRADOR_COSTO_POR_TRADE", 0.0))
        min_trades_test = int(options.get("min_trades_test") or getattr(settings, "CALIBRADOR_MIN_TRADES_TEST", 10))
        max_dd_test = float(options.get("max_dd_test") or getattr(settings, "CALIBRADOR_MAX_DD_TEST", 10.0))
        target = str(options.get("target") or getattr(settings, "CALIBRADOR_TARGET", "sign")).strip().lower()
        max_trade_rate = float(options.get("max_trade_rate") or getattr(settings, "CALIBRADOR_MAX_TRADE_RATE", 0.20))
        min_edge_winrate = float(
            options.get("min_edge_winrate") or getattr(settings, "CALIBRADOR_MIN_EDGE_WINRATE", 0.02)
        )
        forzar_escritura = bool(options.get("forzar_escritura"))

        if count <= 200:
            raise CommandError("ticks-count muy bajo. Usa al menos ~1000 para algo mínimamente estable.")
        if horizon <= 0:
            raise CommandError("horizon-ticks debe ser > 0.")
        if train_n <= 0 or test_n <= 0:
            raise CommandError("train-ticks y test-ticks deben ser > 0.")

        asyncio.run(
            self._run(
                symbol=symbol,
                count=count,
                horizon=horizon,
                train_n=train_n,
                test_n=test_n,
                lam=lam,
                salida=salida,
                no_escribir=no_escribir,
                payout_win=payout_win,
                costo_por_trade=costo_por_trade,
                min_trades_test=min_trades_test,
                max_dd_test=max_dd_test,
                target=target,
                max_trade_rate=max_trade_rate,
                min_edge_winrate=min_edge_winrate,
                forzar_escritura=forzar_escritura,
            )
        )

    async def _run(
        self,
        *,
        symbol: str,
        count: int,
        horizon: int,
        train_n: int,
        test_n: int,
        lam: float,
        salida: str,
        no_escribir: bool,
        payout_win: float = 0.95,
        costo_por_trade: float = 0.0,
        min_trades_test: int = 10,
        max_dd_test: float = 10.0,
        target: str = "sign",
        max_trade_rate: float = 0.20,
        min_edge_winrate: float = 0.02,
        forzar_escritura: bool = False,
    ) -> None:
        self.stdout.write(self.style.SUCCESS(f"[WF] Descargando ticks_history: symbol={symbol} count={count}"))
        async with ClienteDerivWS(token="") as cliente:
            ticks = await cliente.obtener_ticks_history(symbol=symbol, count=count)

        if len(ticks) < (train_n + test_n + horizon + int(settings.MIN_TICKS_CALENTAMIENTO)):
            raise CommandError(
                f"No hay suficientes ticks: {len(ticks)}. Sube ticks-count o baja train/test/horizon."
            )

        # ===== CONSTRUIR FEATURES SECUENCIALES (SIN MIRAR EL FUTURO) =====
        constructor = ConstructorVectorMercado()
        normalizador = NormalizadorOnlinePorVariable(
            alpha=float(settings.NORMALIZACION_ALPHA),
            min_std=float(settings.NORMALIZACION_MIN_STD),
            clip=float(settings.NORMALIZACION_CLIP),
        )

        X_list: list[dict[str, float]] = []
        precios_feat: list[float] = []
        epochs_feat: list[int] = []

        for td in ticks:
            tick = Tick(precio=float(td.precio), epoch=int(td.epoch))
            x = constructor.actualizar_con_tick(tick)
            x_eval = normalizador.actualizar_y_normalizar(x) if bool(settings.NORMALIZAR_VECTOR) else x
            if not constructor.listo_para_operar():
                continue
            X_list.append(x_eval)
            precios_feat.append(float(tick.precio))
            epochs_feat.append(int(tick.epoch))

        if len(X_list) != len(precios_feat):
            raise CommandError("Error de alineación: X_list y precios_feat no coinciden en tamaño.")

        if len(X_list) < (train_n + test_n + horizon + 10):
            raise CommandError("Tras warm-up quedaron pocos puntos. Baja MIN_TICKS_CALENTAMIENTO o sube ticks-count.")

        nombres = list(X_list[0].keys())
        p = len(nombres)
        n_total = len(X_list) - horizon

        X = np.zeros((n_total, p), dtype=float)
        y = np.zeros((n_total,), dtype=float)

        for i in range(n_total):
            xi = X_list[i]
            for j, k in enumerate(nombres):
                X[i, j] = float(xi.get(k, 0.0))
            p0 = float(precios_feat[i])
            p1 = float(precios_feat[i + horizon])
            if target == "return":
                y[i] = 0.0 if p0 == 0 else (p1 - p0) / p0
            else:
                # target por defecto: dirección (clasificación lineal por mínimos cuadrados)
                if p1 > p0:
                    y[i] = 1.0
                elif p1 < p0:
                    y[i] = -1.0
                else:
                    y[i] = 0.0

        # ===== WALK-FORWARD =====
        self.stdout.write(self.style.SUCCESS(f"[WF] Dataset: n={X.shape[0]} p={p} horizon={horizon}"))
        res: list[ResultadoWF] = []

        idx = 0
        w_ultimo = np.zeros((p,), dtype=float)
        # Para evaluación OOS con umbrales: guardamos scores y precios del tramo test por ventana.
        oos_scores: list[np.ndarray] = []
        oos_precios: list[np.ndarray] = []
        while (idx + train_n + test_n) <= X.shape[0]:
            X_tr = X[idx : idx + train_n]
            y_tr = y[idx : idx + train_n]
            X_te = X[idx + train_n : idx + train_n + test_n]
            y_te = y[idx + train_n : idx + train_n + test_n]

            w = _ridge_fit(X_tr, y_tr, lam)
            w_ultimo = w

            scores = X_te @ w
            oos_scores.append(scores.astype(float))
            # precios alineados a X/y (n_total). Para test tomamos el mismo rango:
            pr_te = np.asarray(precios_feat[idx + train_n : idx + train_n + test_n], dtype=float)
            oos_precios.append(pr_te)
            res.append(
                ResultadoWF(
                    start_idx=int(idx),
                    end_idx=int(idx + train_n + test_n),
                    score_media=float(np.mean(scores)),
                    y_media=float(np.mean(y_te)),
                    correlacion=_corr(scores, y_te),
                )
            )

            idx += test_n

        # ===== BUSCAR UMBRALES (CONSTRAINTS) SOBRE OOS =====
        # Estrategia conservadora: umbrales simétricos (thr y -thr) elegidos por grid de cuantiles.
        scores_all = np.concatenate(oos_scores, axis=0) if oos_scores else np.asarray([], dtype=float)
        if scores_all.size < 50:
            raise CommandError("Muy pocos puntos OOS para seleccionar umbrales. Sube ticks-count o ajusta train/test.")

        abs_scores = np.abs(scores_all.astype(float))
        # Cuantiles altos => menos trades. No imponemos "piso" fijo porque el score puede ser pequeño
        # (especialmente si target='return').
        quantiles = [0.70, 0.80, 0.85, 0.90, 0.92, 0.94, 0.96, 0.98, 0.99]
        candidatos = sorted({float(np.quantile(abs_scores, q)) for q in quantiles if 0.0 < q < 1.0})
        # Si todos los scores son ~0, no hay nada que calibrar.
        candidatos = [c for c in candidatos if c > 0.0]
        if not candidatos:
            raise CommandError(
                "El score OOS quedó ~0 para todos los puntos; no se pueden elegir umbrales.\n"
                "Sugerencias: usar --target sign, revisar normalización, o aumentar ticks-count."
            )

        mejor = {
            "umbral_compra": float(settings.UMBRAL_COMPRA),
            "umbral_venta": float(settings.UMBRAL_VENTA),
            "pnl_total": float("-inf"),
            "winrate": 0.0,
            "trades": 0.0,
            "max_drawdown": float("inf"),
            "guardrails_aplicados": True,
        }

        # Winrate de break-even para binaria con stake=1:
        # E[pnl] = w*(payout - cost) + (1-w)*(-1 - cost) = w*(payout+1) - 1 - cost
        # => w >= (1+cost) / (1+payout)
        breakeven_winrate = (1.0 + float(costo_por_trade)) / (1.0 + float(payout_win))
        min_winrate_aceptable = float(breakeven_winrate) + float(min_edge_winrate)

        # Evaluación OOS por ventana (promediamos PnL y sumamos trades).
        for thr in candidatos:
            pnl_total = 0.0
            trades_total = 0.0
            wins_total = 0.0
            max_dd_peor = 0.0
            for sc, pr in zip(oos_scores, oos_precios, strict=False):
                m = _simular_binaria_por_ticks(
                    scores=sc,
                    precios=pr,
                    horizon=horizon,
                    umbral_compra=thr,
                    umbral_venta=-thr,
                    payout_win=payout_win,
                    costo_por_trade=costo_por_trade,
                )
                pnl_total += float(m["pnl_total"])
                trades_total += float(m["trades"])
                wins_total += float(m["wins"])
                max_dd_peor = max(max_dd_peor, float(m["max_drawdown"]))

            winrate = 0.0 if trades_total <= 0 else (wins_total / trades_total)
            if trades_total <= 0.0:
                continue
            trade_rate = float(trades_total) / float(scores_all.size)
            # Constraints para no “forzar” actividad y terminar sobre‑operando.
            if trades_total < float(min_trades_test):
                continue
            if trade_rate > float(max_trade_rate):
                continue
            if max_dd_peor > float(max_dd_test):
                continue
            # Constraint de rentabilidad mínima teórica (según payout/costo) + margen.
            if float(winrate) < float(min_winrate_aceptable):
                continue

            # Objetivo principal: PnL total (con costos).
            if pnl_total > float(mejor["pnl_total"]):
                mejor = {
                    "umbral_compra": float(thr),
                    "umbral_venta": float(-thr),
                    "pnl_total": float(pnl_total),
                    "winrate": float(winrate),
                    "trades": float(trades_total),
                    "max_drawdown": float(max_dd_peor),
                    "guardrails_aplicados": True,
                }

        # Fallback: si ningún umbral pasó guardrails, elegimos el mejor PnL OOS sin restricciones
        # y avisamos. Esto evita devolver "-inf" y permite revisar manualmente antes de activar en real.
        if float(mejor["pnl_total"]) == float("-inf"):
            mejor_relajado = dict(mejor)
            for thr in candidatos:
                pnl_total = 0.0
                trades_total = 0.0
                wins_total = 0.0
                max_dd_peor = 0.0
                for sc, pr in zip(oos_scores, oos_precios, strict=False):
                    m = _simular_binaria_por_ticks(
                        scores=sc,
                        precios=pr,
                        horizon=horizon,
                        umbral_compra=thr,
                        umbral_venta=-thr,
                        payout_win=payout_win,
                        costo_por_trade=costo_por_trade,
                    )
                    pnl_total += float(m["pnl_total"])
                    trades_total += float(m["trades"])
                    wins_total += float(m["wins"])
                    max_dd_peor = max(max_dd_peor, float(m["max_drawdown"]))
                winrate = 0.0 if trades_total <= 0 else (wins_total / trades_total)
                if trades_total <= 0.0:
                    continue
                if pnl_total > float(mejor_relajado["pnl_total"]):
                    mejor_relajado = {
                        "umbral_compra": float(thr),
                        "umbral_venta": float(-thr),
                        "pnl_total": float(pnl_total),
                        "winrate": float(winrate),
                        "trades": float(trades_total),
                        "max_drawdown": float(max_dd_peor),
                        "guardrails_aplicados": False,
                    }
            mejor = mejor_relajado
            if float(mejor["pnl_total"]) == float("-inf"):
                raise CommandError(
                    "No se generó ningún trade en la evaluación OOS para ningún umbral candidato.\n"
                    "Sugerencias:\n"
                    "- Sube ticks-count (ej: 20000+)\n"
                    "- Baja train/test para tener más ventanas OOS\n"
                    "- Reduce costos (CALIBRADOR_COSTO_POR_TRADE) si estás sobre-penalizando\n"
                    "- Revisa NORMALIZACION_ALPHA/CLIP si el score queda demasiado comprimido"
                )

        # ===== EXPORTAR PESOS =====
        pesos = {str(k): float(w_ultimo[j]) for j, k in enumerate(nombres)}
        resumen = {
            "symbol": symbol,
            "ticks_count": int(count),
            "horizon_ticks": int(horizon),
            "train_ticks": int(train_n),
            "test_ticks": int(test_n),
            "lambda_ridge": float(lam),
            "n_muestras": int(X.shape[0]),
            "p_features": int(p),
            "evaluacion_oos": {
                "payout_win": float(payout_win),
                "costo_por_trade": float(costo_por_trade),
                "breakeven_winrate": float(breakeven_winrate),
                "min_edge_winrate": float(min_edge_winrate),
                "min_winrate_aceptable": float(min_winrate_aceptable),
                "min_trades_test": int(min_trades_test),
                "max_dd_test": float(max_dd_test),
                "target": str(target),
                "max_trade_rate": float(max_trade_rate),
                "umbral_compra_recomendado": float(mejor["umbral_compra"]),
                "umbral_venta_recomendado": float(mejor["umbral_venta"]),
                "trades_oos": float(mejor["trades"]),
                "winrate_oos": float(mejor["winrate"]),
                "pnl_total_oos": float(mejor["pnl_total"]),
                "max_drawdown_oos": float(mejor["max_drawdown"]),
                "guardrails_aplicados": bool(mejor.get("guardrails_aplicados", True)),
            },
            "ventanas": [r.__dict__ for r in res[-10:]],  # SOLO LAS ÚLTIMAS 10 PARA NO HACERLO ENORME
        }

        payload = {"resumen": resumen, "pesos": pesos}

        self.stdout.write(self.style.SUCCESS("[WF] Pesos (última ventana)"))
        for k, v in sorted(pesos.items(), key=lambda kv: abs(float(kv[1])), reverse=True)[:10]:
            self.stdout.write(f"  {k}: {v:+.6f}")

        ev = resumen.get("evaluacion_oos") or {}
        if isinstance(ev, dict):
            tag = "con guardrails" if bool(ev.get("guardrails_aplicados", True)) else "SIN guardrails (fallback)"
            self.stdout.write(self.style.SUCCESS(f"[WF] Recomendación (OOS, {tag})"))
            self.stdout.write(
                "  "
                f"umbral_compra={ev.get('umbral_compra_recomendado')} "
                f"umbral_venta={ev.get('umbral_venta_recomendado')} "
                f"trades={ev.get('trades_oos')} "
                f"winrate={ev.get('winrate_oos')} "
                f"pnl_total={ev.get('pnl_total_oos')} "
                f"max_dd={ev.get('max_drawdown_oos')}"
            )
            self.stdout.write(
                "  "
                f"breakeven_winrate={ev.get('breakeven_winrate')} "
                f"min_winrate_aceptable={ev.get('min_winrate_aceptable')}"
            )

        if not no_escribir:
            # Seguridad: no escribir un modelo "perdedor" o sin guardrails salvo confirmación explícita.
            if not forzar_escritura:
                if not bool(mejor.get("guardrails_aplicados", True)):
                    raise CommandError(
                        "El calibrador encontró umbrales solo con fallback (SIN guardrails). No se escribirá el archivo.\n"
                        "Si de verdad quieres escribirlo, re-ejecuta con --forzar-escritura."
                    )
                if float(mejor.get("pnl_total", 0.0)) <= 0.0:
                    raise CommandError(
                        "El PnL OOS recomendado es <= 0. No se escribirá el archivo para proteger el modo real.\n"
                        "Ajusta parámetros (payout/costo/ventanas) o usa --forzar-escritura bajo tu responsabilidad."
                    )

            path = Path(salida)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"[WF] Guardado: {path}"))


