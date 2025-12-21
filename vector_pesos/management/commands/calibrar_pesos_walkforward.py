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

    def handle(self, *args, **options) -> None:  # noqa: ANN001
        symbol = (options.get("symbol") or settings.DERIV_SYMBOL).strip()
        count = int(options.get("ticks_count") or settings.CALIBRADOR_TICKS_COUNT)
        horizon = int(options.get("horizon_ticks") or settings.CALIBRADOR_HORIZON_TICKS)
        train_n = int(options.get("train_ticks") or settings.CALIBRADOR_TRAIN_TICKS)
        test_n = int(options.get("test_ticks") or settings.CALIBRADOR_TEST_TICKS)
        lam = float(options.get("lambda_ridge") or settings.CALIBRADOR_LAMBDA_RIDGE)
        salida = str(options.get("salida") or settings.PESOS_ARCHIVO)
        no_escribir = bool(options.get("no_escribir"))

        if count <= 200:
            raise CommandError("ticks-count muy bajo. Usa al menos ~1000 para algo mínimamente estable.")
        if horizon <= 0:
            raise CommandError("horizon-ticks debe ser > 0.")
        if train_n <= 0 or test_n <= 0:
            raise CommandError("train-ticks y test-ticks deben ser > 0.")

        asyncio.run(self._run(symbol=symbol, count=count, horizon=horizon, train_n=train_n, test_n=test_n, lam=lam, salida=salida, no_escribir=no_escribir))

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
        precios: list[float] = []

        for td in ticks:
            precios.append(float(td.precio))
            x = constructor.actualizar_con_tick(Tick(precio=float(td.precio), epoch=int(td.epoch)))
            x_eval = normalizador.actualizar_y_normalizar(x) if bool(settings.NORMALIZAR_VECTOR) else x
            if not constructor.listo_para_operar():
                continue
            X_list.append(x_eval)

        # Alinear precios con X_list (se recortó warm-up)
        # Asumimos que el warm-up consumió (len(ticks) - len(X_list)) ticks aproximadamente.
        # Para robustez, reconstruimos precios en paralelo:
        precios_feat = precios[-len(X_list):]

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
            y[i] = 0.0 if p0 == 0 else (p1 - p0) / p0

        # ===== WALK-FORWARD =====
        self.stdout.write(self.style.SUCCESS(f"[WF] Dataset: n={X.shape[0]} p={p} horizon={horizon}"))
        res: list[ResultadoWF] = []

        idx = 0
        w_ultimo = np.zeros((p,), dtype=float)
        while (idx + train_n + test_n) <= X.shape[0]:
            X_tr = X[idx : idx + train_n]
            y_tr = y[idx : idx + train_n]
            X_te = X[idx + train_n : idx + train_n + test_n]
            y_te = y[idx + train_n : idx + train_n + test_n]

            w = _ridge_fit(X_tr, y_tr, lam)
            w_ultimo = w

            scores = X_te @ w
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
            "ventanas": [r.__dict__ for r in res[-10:]],  # SOLO LAS ÚLTIMAS 10 PARA NO HACERLO ENORME
        }

        payload = {"resumen": resumen, "pesos": pesos}

        self.stdout.write(self.style.SUCCESS("[WF] Pesos (última ventana)"))
        for k, v in sorted(pesos.items(), key=lambda kv: abs(float(kv[1])), reverse=True)[:10]:
            self.stdout.write(f"  {k}: {v:+.6f}")

        if not no_escribir:
            path = Path(salida)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"[WF] Guardado: {path}"))


