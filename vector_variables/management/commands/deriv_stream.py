from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from gestion_riesgo.gestor_riesgo import GestorRiesgo
from gestion_riesgo.models import BalanceDerivSnapshot, Cuenta, Operacion, OperacionDeriv
from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS, dormir_segundos
from vector_pesos.gestor_pesos import GestorPesos
from vector_pesos.senal import evaluar_senal
from vector_pesos.adaptativo import AdaptadorUmbralOnline
from vector_variables.constructor_vector import ConstructorVectorMercado, Tick
from vector_variables.normalizacion import NormalizadorOnlinePorVariable


@dataclass
class PosicionPaper:
    """
    POSICIÓN SIMULADA PARA VALIDAR RIESGO/DRAWDOWN SIN EJECUTAR ÓRDENES REALES.
    """

    direccion: str  # "LARGO" | "CORTO"
    precio_entrada: float
    tamanio: float
    stop_distancia: float
    operacion_id: int


class Command(BaseCommand):
    help = "Consume ticks de Deriv, construye vector x, evalúa w^T x y aplica gestión de riesgo (single process)."

    @staticmethod
    def _parse_horas_bloqueadas(spec: str) -> set[int]:
        """
        spec: "2-3,22" (rangos inclusivos). Espacios permitidos.
        Retorna horas [0..23]. Entradas inválidas se ignoran.
        """
        raw = (spec or "").strip()
        if not raw:
            return set()
        out: set[int] = set()
        for part in raw.replace(";", ",").replace(" ", ",").split(","):
            tok = part.strip()
            if not tok:
                continue
            if "-" in tok:
                a_s, b_s = tok.split("-", 1)
                try:
                    a = int(a_s.strip())
                    b = int(b_s.strip())
                except Exception:
                    continue
                lo, hi = (a, b) if a <= b else (b, a)
                for h in range(lo, hi + 1):
                    if 0 <= h <= 23:
                        out.add(h)
            else:
                try:
                    h = int(tok)
                except Exception:
                    continue
                if 0 <= h <= 23:
                    out.add(h)
        return out

    @staticmethod
    def _hora_local(epoch: int) -> int:
        tz = getattr(settings, "TIME_ZONE", "UTC") or "UTC"
        return datetime.fromtimestamp(int(epoch), tz=ZoneInfo(tz)).hour

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--symbol", type=str, default=None, help="Símbolo Deriv (ej: R_100).")
        parser.add_argument(
            "--max-ticks",
            type=int,
            default=2000,
            help="Máximo de ticks a procesar (por defecto: 2000).",
        )
        parser.add_argument(
            "--max-segundos",
            type=int,
            default=300,
            help="Máximo de segundos de ejecución (por defecto: 300).",
        )
        parser.add_argument(
            "--max-reintentos",
            type=int,
            default=10,
            help="Máximo de reintentos de conexión WebSocket (por defecto: 10).",
        )
        parser.add_argument(
            "--ilimitado",
            action="store_true",
            help="Ejecuta sin límites (NO recomendado).",
        )
        parser.add_argument(
            "--permitir-sin-venv",
            action="store_true",
            help="Permite ejecutar sin entorno virtual (NO recomendado).",
        )
        parser.add_argument(
            "--real",
            action="store_true",
            help="Habilita ejecución REAL en Deriv (requiere DERIV_MODO_REAL=True y DERIV_CONFIRMAR_REAL=SI).",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN001
        symbol = (options.get("symbol") or settings.DERIV_SYMBOL).strip()
        ilimitado = bool(options.get("ilimitado"))
        permitir_sin_venv = bool(options.get("permitir_sin_venv"))
        max_ticks = int(options.get("max_ticks") or 0)
        max_segundos = int(options.get("max_segundos") or 0)
        max_reintentos = int(options.get("max_reintentos") or 0)

        if not permitir_sin_venv and not self._en_entorno_virtual():
            raise CommandError(
                "Este comando DEBE ejecutarse dentro de un entorno virtual.\n"
                "Activa `.venv` y vuelve a intentar (o usa `--permitir-sin-venv` bajo tu responsabilidad)."
            )

        # POR DEFECTO NO PERMITIMOS EJECUCIÓN ILIMITADA.
        if not ilimitado and (max_ticks <= 0 and max_segundos <= 0):
            raise CommandError("Debes definir `--max-ticks` y/o `--max-segundos` (no se permite ilimitado por defecto).")

        ejecutar_real = bool(options.get("real"))
        asyncio.run(
            self._run(
                symbol,
                max_ticks=max_ticks,
                max_segundos=max_segundos,
                max_reintentos=max_reintentos,
                ilimitado=ilimitado,
                ejecutar_real=ejecutar_real,
            )
        )

    async def _run(
        self,
        symbol: str,
        *,
        max_ticks: int,
        max_segundos: int,
        max_reintentos: int,
        ilimitado: bool,
        ejecutar_real: bool = False,
    ) -> None:
        # ===== INICIALIZACIÓN DE CAPAS =====
        constructor = ConstructorVectorMercado()
        gestor_pesos = GestorPesos.con_pesos_fijos_por_defecto(ruta_archivo=getattr(settings, "PESOS_ARCHIVO", None))
        gestor_riesgo = GestorRiesgo(
            capital_inicial=settings.CAPITAL_INICIAL,
            max_riesgo_por_operacion=settings.MAX_RIESGO_POR_OPERACION,
            max_drawdown=settings.MAX_DRAWDOWN,
        )
        normalizador = NormalizadorOnlinePorVariable(
            alpha=float(settings.NORMALIZACION_ALPHA),
            min_std=float(settings.NORMALIZACION_MIN_STD),
            clip=float(settings.NORMALIZACION_CLIP),
        )

        adaptativo: AdaptadorUmbralOnline | None = None
        if bool(getattr(settings, "ADAPTATIVO_HABILITADO", False)):
            adaptativo = AdaptadorUmbralOnline(
                thresholds=list(getattr(settings, "ADAPTATIVO_UMBRALES", [])),
                payout_win=float(getattr(settings, "CALIBRADOR_PAYOUT_WIN", 0.95)),
                costo_por_trade=float(getattr(settings, "CALIBRADOR_COSTO_POR_TRADE", 0.0)),
                min_trades=int(getattr(settings, "ADAPTATIVO_MIN_TRADES", 60)),
                edge_margin=float(getattr(settings, "ADAPTATIVO_EDGE_MARGIN", 0.02)),
                archivo_estado=str(getattr(settings, "ADAPTATIVO_ARCHIVO", "vector_pesos/umbral_online.json")),
            )

        posicion: PosicionPaper | None = None
        operacion_abierta: Operacion | None = None
        contrato_abierto_id: int | None = None
        esperando: dict | None = None
        esperando_desde: float = 0.0
        ultimo_open_contract: float = 0.0
        watchdog_open_contract_intentos: int = 0
        ultimo_warn_duracion: float = 0.0

        # ===== PERSISTENCIA: CUENTA =====
        cuenta = await sync_to_async(self._obtener_o_crear_cuenta, thread_sensitive=True)(
            simbolo=symbol, gestor_riesgo=gestor_riesgo
        )

        # REINTENTOS CONTROLADOS PARA PRODUCCIÓN (REDES/PROXIES/FIREWALLS/TEMPORALES).
        intentos = 0
        ticks_procesados = 0
        inicio = time.monotonic()
        ultimo_persist = 0.0
        ultimo_historial = 0.0
        ultimo_log = 0.0
        ultimo_balance_snapshot = 0.0
        ultimo_balance_poll = 0.0
        balance_moneda = ""
        balance_poll_cada_seg = float(getattr(settings, "DERIV_BALANCE_POLL_CADA_SEG", 60.0))
        contract_types_permitidos = {str(x).strip().upper() for x in getattr(settings, "DERIV_CONTRACT_TYPES_PERMITIDOS", []) if str(x).strip()}
        if not contract_types_permitidos:
            contract_types_permitidos = {"PUT", "CALL"}
        horas_bloqueadas = self._parse_horas_bloqueadas(str(getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""))

        # MODO REAL: DOBLE BLOQUEO (FLAG + ENV CONFIRMACIÓN).
        modo_real = bool(ejecutar_real) and bool(settings.DERIV_MODO_REAL) and (settings.DERIV_CONFIRMAR_REAL == "SI")
        if bool(ejecutar_real) and not modo_real:
            raise CommandError(
                "Modo real solicitado pero no está confirmado.\n"
                "Requisitos: --real + DERIV_MODO_REAL=True + DERIV_CONFIRMAR_REAL=SI\n"
                f"Valores efectivos: DERIV_MODO_REAL={settings.DERIV_MODO_REAL} "
                f"DERIV_CONFIRMAR_REAL={settings.DERIV_CONFIRMAR_REAL!r}"
            )
        if modo_real and not settings.DERIV_API_TOKEN:
            raise CommandError("Modo real requiere DERIV_API_TOKEN con permisos de 'trade'.")

        # ===== CONFIG EFECTIVA (LOG 1 VEZ) =====
        pesos_archivo = getattr(settings, "PESOS_ARCHIVO", "") or ""
        pesos_info = "PESOS_ARCHIVO=<vacío>"
        if pesos_archivo:
            try:
                existe = os.path.exists(pesos_archivo)
                mtime = os.path.getmtime(pesos_archivo) if existe else None
                pesos_info = f"PESOS_ARCHIVO={pesos_archivo} existe={existe} mtime={mtime}"
            except Exception:
                pesos_info = f"PESOS_ARCHIVO={pesos_archivo} (error al inspeccionar archivo)"

        # Nota: stdout sin style para que quede grepeable en `journalctl | grep`.
        stake_fijo_cfg = getattr(settings, "DERIV_STAKE_FIJO", None)
        self.stdout.write(
            "[CFG] "
            f"modo_real={modo_real} symbol={symbol} "
            f"dur_ticks={int(settings.DERIV_DURACION_TICKS)} "
            f"umbral_compra={float(settings.UMBRAL_COMPRA)} umbral_venta={float(settings.UMBRAL_VENTA)} "
            f"normalizar={bool(settings.NORMALIZAR_VECTOR)} "
            f"alpha={float(settings.NORMALIZACION_ALPHA)} clip={float(settings.NORMALIZACION_CLIP)} "
            f"balance_poll_cada_seg={balance_poll_cada_seg:.0f} "
            f"min_stake={float(getattr(settings,'DERIV_MIN_STAKE',1.0))} "
            f"stake_fijo={float(stake_fijo_cfg) if stake_fijo_cfg is not None else '-'} "
            f"contract_types={','.join(sorted(contract_types_permitidos))} "
            f"horas_bloqueadas={','.join(str(h) for h in sorted(horas_bloqueadas)) if horas_bloqueadas else '-'} "
            + pesos_info
            + f" adaptativo={bool(adaptativo is not None)}"
            + (
                f" adapt_modo_sin_evidencia={getattr(settings,'ADAPTATIVO_MODO_SIN_EVIDENCIA','no_operar')}"
                f" adapt_warmup={float(getattr(settings,'ADAPTATIVO_UMBRAL_WARMUP',0.09))}"
                f" adapt_min_trades={int(getattr(settings,'ADAPTATIVO_MIN_TRADES',60))}"
                f" adapt_edge_margin={float(getattr(settings,'ADAPTATIVO_EDGE_MARGIN',0.02))}"
                if adaptativo is not None
                else ""
            )
        )

        def _limite_alcanzado() -> bool:
            if ilimitado:
                return False
            if max_ticks > 0 and ticks_procesados >= max_ticks:
                return True
            if max_segundos > 0 and (time.monotonic() - inicio) >= float(max_segundos):
                return True
            return False

        while True:
            if _limite_alcanzado():
                self.stdout.write(self.style.SUCCESS("[FIN] Límite alcanzado. Deteniendo stream."))
                return

            intentos += 1
            if not ilimitado and max_reintentos > 0 and intentos > max_reintentos:
                raise CommandError("[WS] Se alcanzó el máximo de reintentos. Abortando para evitar ejecución ilimitada.")

            self.stdout.write(
                self.style.SUCCESS(
                    f"[WS] Conectando a Deriv | intento={intentos} | symbol={symbol} | app_id={settings.DERIV_APP_ID}"
                )
            )
            try:
                async with ClienteDerivWS(token=settings.DERIV_API_TOKEN) as cliente:
                    # BALANCE REAL SOLO SI HAY TOKEN (AUTORIZACIÓN).
                    incluir_balance = bool(settings.DERIV_API_TOKEN)
                    if incluir_balance:
                        self.stdout.write(self.style.SUCCESS("[WS] Suscrito (ticks + balance). Esperando eventos..."))
                    else:
                        self.stderr.write(self.style.WARNING("[WS] Sin DERIV_API_TOKEN: no se puede suscribir a balance."))
                        self.stdout.write(self.style.SUCCESS("[WS] Suscrito (solo ticks). Esperando ticks..."))

                    # Forzar refresh de balance (one-shot) para evitar quedarse bloqueado por pausas vencidas
                    # cuando Deriv no emite updates de balance por stream.
                    ultimo_balance_poll = time.monotonic()

                    # Si veníamos con un contrato abierto de una conexión previa, re-suscribir.
                    if modo_real and contrato_abierto_id is not None:
                        try:
                            await cliente.enviar(
                                {"proposal_open_contract": 1, "contract_id": int(contrato_abierto_id), "subscribe": 1}
                            )
                            self.stderr.write(
                                f"[TRADING] Re-suscripción contrato abierto tras reconexión: contract_id={int(contrato_abierto_id)}"
                            )
                            ultimo_open_contract = time.monotonic()
                        except Exception as e:
                            self.stderr.write(f"[TRADING] Falló re-suscripción open_contract: {e}")

                    async for ev in cliente.stream_eventos(symbol, incluir_balance=incluir_balance):
                        # Balance poll periódico (one-shot). Esto garantiza recalcular ciclos/drawdown aunque
                        # Deriv no envíe mensajes `balance` cuando el monto no cambia.
                        if incluir_balance and balance_poll_cada_seg > 0:
                            now_m = time.monotonic()
                            if (now_m - ultimo_balance_poll) >= float(balance_poll_cada_seg):
                                try:
                                    await cliente.enviar({"balance": 1})
                                finally:
                                    ultimo_balance_poll = now_m

                        if ev.get("tipo") == "balance":
                            bal = ev["balance"]
                            # EN MODO REAL: BLOQUEO/DRAWDOWN DEBE BASARSE SOLO EN BALANCE REAL DERIV.
                            # EVITA MEZCLAR HISTÓRICOS "PAPER" CON BALANCE REAL (ESO TE BLOQUEA INJUSTAMENTE).
                            if modo_real:
                                balance_val = float(bal.balance)
                                currency = str(bal.currency or "")

                                async def _actualizar_balance_real() -> None:
                                    prev = await sync_to_async(
                                        lambda: Cuenta.objects.filter(id=cuenta.id).values(
                                            "max_balance_deriv_historico",
                                            "bloqueado",
                                            "ciclo_balance_inicio",
                                            "ciclo_inicio_epoch",
                                            "ciclo_pausa_hasta_epoch",
                                        ).first(),
                                        thread_sensitive=True,
                                    )()
                                    prev_max = float(prev["max_balance_deriv_historico"]) if prev and prev.get("max_balance_deriv_historico") is not None else balance_val
                                    prev_bloqueado = bool(prev.get("bloqueado")) if prev else False
                                    nuevo_max = max(prev_max, balance_val)
                                    drawdown = 0.0 if nuevo_max <= 0 else (1.0 - (balance_val / nuevo_max))

                                    dd_max = float(settings.MAX_DRAWDOWN)
                                    dd_hyst = float(getattr(settings, "MAX_DRAWDOWN_HISTERESIS", 0.0))
                                    dd_hyst = max(0.0, min(dd_hyst, dd_max))  # clamp defensivo
                                    dd_unblock = max(0.0, dd_max - dd_hyst)

                                    # ===== CICLOS (OPCIONAL) =====
                                    ahora_epoch = int(time.time())
                                    ciclo_habil = bool(getattr(settings, "CICLO_HABILITADO", False))
                                    ciclo_tp = float(getattr(settings, "CICLO_TAKE_PROFIT_PCT", 0.015))
                                    ciclo_sl = float(getattr(settings, "CICLO_STOPLOSS_PCT", 0.010))
                                    pausa_tp = int(getattr(settings, "CICLO_PAUSA_TP_SEG", 86400))
                                    pausa_sl = int(getattr(settings, "CICLO_PAUSA_SL_SEG", 3600))

                                    ciclo_balance_inicio = float(prev.get("ciclo_balance_inicio")) if (prev and prev.get("ciclo_balance_inicio") is not None) else None
                                    ciclo_pausa_hasta = int(prev.get("ciclo_pausa_hasta_epoch")) if (prev and prev.get("ciclo_pausa_hasta_epoch") is not None) else None

                                    riesgo_motivo = ""
                                    ciclo_evento = ""
                                    ciclo_bloqueado = False
                                    nuevo_ciclo_balance_inicio = ciclo_balance_inicio
                                    nuevo_ciclo_inicio_epoch = int(prev.get("ciclo_inicio_epoch")) if (prev and prev.get("ciclo_inicio_epoch") is not None) else None
                                    nuevo_ciclo_pausa_hasta = ciclo_pausa_hasta

                                    if ciclo_habil:
                                        # Si estamos en pausa, bloquear.
                                        if ciclo_pausa_hasta is not None and ahora_epoch < ciclo_pausa_hasta:
                                            ciclo_bloqueado = True
                                            riesgo_motivo = f"PAUSA_CICLO_HASTA_{ciclo_pausa_hasta}"
                                            ciclo_evento = "PAUSA"
                                        else:
                                            # Si terminó la pausa, limpiar y arrancar ciclo con baseline fresco.
                                            if ciclo_pausa_hasta is not None and ahora_epoch >= ciclo_pausa_hasta:
                                                nuevo_ciclo_pausa_hasta = None
                                                nuevo_ciclo_balance_inicio = None
                                                nuevo_ciclo_inicio_epoch = None

                                            if nuevo_ciclo_balance_inicio is None:
                                                nuevo_ciclo_balance_inicio = float(balance_val)
                                                nuevo_ciclo_inicio_epoch = int(ahora_epoch)
                                                ciclo_evento = "CICLO_INICIADO"

                                            # Evaluar PnL % del ciclo
                                            if nuevo_ciclo_balance_inicio and nuevo_ciclo_balance_inicio > 0:
                                                pnl_pct = (float(balance_val) / float(nuevo_ciclo_balance_inicio)) - 1.0
                                                if pnl_pct >= float(ciclo_tp):
                                                    nuevo_ciclo_pausa_hasta = int(ahora_epoch + max(0, pausa_tp))
                                                    nuevo_ciclo_balance_inicio = None
                                                    nuevo_ciclo_inicio_epoch = None
                                                    ciclo_bloqueado = True
                                                    riesgo_motivo = f"TAKE_PROFIT_{float(ciclo_tp):.4f}_PAUSA_{int(pausa_tp)}s"
                                                    ciclo_evento = "TAKE_PROFIT"
                                                elif pnl_pct <= -float(ciclo_sl):
                                                    nuevo_ciclo_pausa_hasta = int(ahora_epoch + max(0, pausa_sl))
                                                    nuevo_ciclo_balance_inicio = None
                                                    nuevo_ciclo_inicio_epoch = None
                                                    ciclo_bloqueado = True
                                                    riesgo_motivo = f"STOPLOSS_{float(ciclo_sl):.4f}_PAUSA_{int(pausa_sl)}s"
                                                    ciclo_evento = "STOPLOSS"
                                                else:
                                                    riesgo_motivo = "CICLO_ACTIVO"
                                                    if not ciclo_evento:
                                                        ciclo_evento = "EN_CURSO"

                                    # ===== DRAWDOWN GLOBAL (OPCIONAL) =====
                                    dd_habil = bool(getattr(settings, "DRAWDOWN_GLOBAL_HABILITADO", True))

                                    # Histéresis: si ya está bloqueado, requerimos recuperación adicional para desbloquear.
                                    if dd_habil:
                                        if prev_bloqueado:
                                            bloqueado_dd = not (drawdown <= dd_unblock)
                                        else:
                                            bloqueado_dd = bool(drawdown >= dd_max)
                                    else:
                                        bloqueado_dd = False

                                    bloqueado_real = bool(ciclo_bloqueado or bloqueado_dd)
                                    if not riesgo_motivo:
                                        riesgo_motivo = "DRAWDOWN" if bloqueado_dd else "OK"

                                    # Log sólo cuando cambia el estado (evita spam).
                                    if (not prev_bloqueado) and bloqueado_real:
                                        if ciclo_bloqueado and ciclo_evento in {"TAKE_PROFIT", "STOPLOSS", "PAUSA"}:
                                            self.stderr.write(f"[RISK] BLOQUEO_POR_CICLO motivo={riesgo_motivo} balance={balance_val:.2f}")
                                        elif bloqueado_dd:
                                            bal_req = (nuevo_max * (1.0 - dd_unblock)) if nuevo_max > 0 else None
                                            self.stderr.write(
                                                "[RISK] BLOQUEO_POR_DRAWDOWN "
                                                f"drawdown={drawdown:.6f} umbral={dd_max:.6f} "
                                                f"balance={balance_val:.2f} max={nuevo_max:.2f} "
                                                + (f"balance_desbloqueo>={bal_req:.3f} (histeresis={dd_hyst:.6f})" if bal_req is not None else "")
                                            )
                                    if prev_bloqueado and (not bloqueado_real):
                                        self.stderr.write(f"[RISK] DESBLOQUEO motivo={riesgo_motivo} balance={balance_val:.2f}")

                                    await sync_to_async(
                                        lambda: Cuenta.objects.filter(id=cuenta.id).update(
                                            balance_deriv=balance_val,
                                            moneda_deriv=currency,
                                            max_balance_deriv_historico=nuevo_max,
                                            bloqueado=bloqueado_real,
                                            riesgo_motivo=riesgo_motivo,
                                            ciclo_balance_inicio=nuevo_ciclo_balance_inicio,
                                            ciclo_inicio_epoch=nuevo_ciclo_inicio_epoch,
                                            ciclo_pausa_hasta_epoch=nuevo_ciclo_pausa_hasta,
                                            ciclo_ultimo_evento=ciclo_evento,
                                        ),
                                        thread_sensitive=True,
                                    )()

                                    gestor_riesgo.capital_actual = balance_val
                                    gestor_riesgo.max_capital_historico = nuevo_max
                                    gestor_riesgo.bloqueado = bloqueado_real

                                await _actualizar_balance_real()

                                # ===== SNAPSHOT PARA GRÁFICA (MUESTREO) =====
                                ahora_s = time.monotonic()
                                cada = float(getattr(settings, "BALANCE_SNAPSHOT_CADA_SEG", 60))
                                if cada <= 0:
                                    cada = 60.0
                                if (ahora_s - ultimo_balance_snapshot) >= cada:
                                    ultimo_balance_snapshot = ahora_s
                                    try:
                                        await sync_to_async(
                                            lambda: BalanceDerivSnapshot.objects.create(
                                                cuenta_id=int(cuenta.id),
                                                balance=float(balance_val),
                                                moneda=str(currency),
                                                epoch=int(time.time()),
                                            ),
                                            thread_sensitive=True,
                                        )()
                                    except Exception:
                                        # No rompe trading si falla el storage de la gráfica.
                                        pass
                            else:
                                await sync_to_async(
                                    lambda: Cuenta.objects.filter(id=cuenta.id).update(
                                        balance_deriv=float(bal.balance),
                                        moneda_deriv=str(bal.currency),
                                    ),
                                    thread_sensitive=True,
                                )()
                                # (NO REAL) PUEDE USAR ESTE VALOR COMO BASE DE RIESGO PARA SIMULACIÓN.
                                gestor_riesgo.capital_actual = float(bal.balance)
                                gestor_riesgo.max_capital_historico = max(
                                    float(gestor_riesgo.max_capital_historico), float(bal.balance)
                                )
                            balance_moneda = str(bal.currency or "")
                            continue

                        # RESPUESTAS DE TRADING / HISTORIAL
                        if ev.get("tipo") == "profit_table":
                            if modo_real:
                                # Si el contrato abierto ya aparece como vendido en profit_table,
                                # liberar `contrato_abierto_id` para no quedar bloqueados por siempre.
                                try:
                                    if contrato_abierto_id is not None:
                                        tabla = (ev.get("raw") or {}).get("profit_table") or {}
                                        trans = tabla.get("transactions") or []
                                        for t in trans:
                                            cid = t.get("contract_id")
                                            if cid is None:
                                                continue
                                            if int(cid) != int(contrato_abierto_id):
                                                continue
                                            if t.get("sell_time"):
                                                self.stderr.write(
                                                    f"[TRADING] profit_table indica contrato cerrado. Liberando contract_id={int(contrato_abierto_id)}"
                                                )
                                                contrato_abierto_id = None
                                                break
                                except Exception:
                                    pass
                                await self._procesar_profit_table(cuenta_id=int(cuenta.id), raw=ev["raw"])
                            continue
                        if ev.get("tipo") == "proposal_open_contract":
                            if modo_real:
                                contrato = ev["raw"].get("proposal_open_contract") or {}
                                await self._procesar_open_contract(cuenta_id=int(cuenta.id), simbolo=symbol, contrato=contrato)
                                ultimo_open_contract = time.monotonic()
                                watchdog_open_contract_intentos = 0

                                # ===== APRENDIZAJE ONLINE (AL CERRAR CONTRATO) =====
                                if adaptativo is not None and int(contrato.get("is_sold", 0)) == 1:
                                    cid = contrato.get("contract_id")
                                    profit = contrato.get("profit")
                                    if cid is not None and profit is not None:
                                        def _leer_senal_valor() -> float | None:
                                            fila = OperacionDeriv.objects.filter(contract_id=int(cid)).values("senal_valor").first()
                                            if not fila:
                                                return None
                                            v = fila.get("senal_valor")
                                            return float(v) if v is not None else None

                                        s0 = await sync_to_async(_leer_senal_valor, thread_sensitive=True)()
                                        if s0 is not None:
                                            adaptativo.registrar_trade_cerrado(
                                                score_entrada=float(s0),
                                                gano=(float(profit) > 0.0),
                                            )
                                # SI SE CIERRA, LIBERAR PARA PERMITIR NUEVA OPERACIÓN.
                                if int(contrato.get("is_sold", 0)) == 1:
                                    contrato_abierto_id = None
                                    # SI EL PROFIT AÚN NO LLEGÓ, FORZAR UNA ACTUALIZACIÓN DE PROFIT_TABLE YA.
                                    await cliente.enviar(
                                        {
                                            "profit_table": 1,
                                            "description": 1,
                                            "limit": int(settings.DERIV_HISTORIAL_LIMIT),
                                        }
                                    )
                            continue
                        if ev.get("tipo") == "proposal" and esperando and esperando.get("tipo") == "proposal":
                            prop = ev["raw"].get("proposal") or {}
                            proposal_id = prop.get("id")
                            ask = float(prop.get("ask_price") or esperando.get("stake") or 0.0)
                            if proposal_id:
                                self.stderr.write(f"[TRADING] proposal OK id={proposal_id} ask={ask:.4f} -> enviando buy")
                                await cliente.enviar({"buy": proposal_id, "price": ask})
                                esperando["tipo"] = "buy"
                                esperando_desde = time.monotonic()
                            continue
                        if ev.get("tipo") == "buy" and esperando and esperando.get("tipo") == "buy":
                            buy = ev["raw"].get("buy") or {}
                            contrato_id = buy.get("contract_id")
                            trans_id = buy.get("transaction_id")
                            buy_price = float(buy.get("buy_price") or 0.0)
                            if contrato_id:
                                contrato_abierto_id = int(contrato_id)
                                self.stderr.write(
                                    f"[TRADING] buy OK contract_id={int(contrato_id)} transaction_id={trans_id} buy_price={buy_price:.4f}"
                                )
                                await cliente.enviar({"proposal_open_contract": 1, "contract_id": int(contrato_id), "subscribe": 1})
                                ultimo_open_contract = time.monotonic()
                                await sync_to_async(self._db_registrar_compra_deriv, thread_sensitive=True)(
                                    cuenta_id=int(cuenta.id),
                                    simbolo=symbol,
                                    contract_id=int(contrato_id),
                                    transaction_id=int(trans_id) if trans_id is not None else None,
                                    buy_price=buy_price,
                                    moneda=balance_moneda,
                                    senal_valor=float(esperando.get("senal_valor")) if esperando.get("senal_valor") is not None else None,
                                    umbral_usado=float(esperando.get("umbral_usado")) if esperando.get("umbral_usado") is not None else None,
                                    pesos_usados=esperando.get("pesos_usados"),
                                    senal_top_contribuciones=esperando.get("senal_top_contribuciones"),
                                )
                            esperando = None
                            continue

                        tick_deriv = ev["tick"]
                        ticks_procesados += 1
                        if _limite_alcanzado():
                            self.stdout.write(self.style.SUCCESS("[FIN] Límite alcanzado. Cerrando conexión."))
                            return

                        tick = Tick(precio=tick_deriv.precio, epoch=tick_deriv.epoch)
                        x = constructor.actualizar_con_tick(tick)
                        x_eval = (
                            normalizador.actualizar_y_normalizar(x)
                            if bool(settings.NORMALIZAR_VECTOR)
                            else x
                        )

                        # ===== WATCHDOG TRADING REAL =====
                        # Evita quedarse días sin operar por un estado "esperando" atascado tras un timeout/error WS.
                        ahora_wd = time.monotonic()
                        if modo_real and esperando is not None and esperando_desde > 0:
                            if (ahora_wd - esperando_desde) >= float(settings.DERIV_TIMEOUT_PROPUESTA_SEG):
                                self.stderr.write(
                                    f"[TRADING] Timeout esperando '{esperando.get('tipo')}'. Reset estado. contract_abierto_id={contrato_abierto_id}"
                                )
                                esperando = None
                                esperando_desde = 0.0

                        if modo_real and contrato_abierto_id is not None and ultimo_open_contract > 0:
                            if (ahora_wd - ultimo_open_contract) >= float(settings.DERIV_TIMEOUT_CONTRATO_SEG):
                                # No liberamos a ciegas: pedimos profit_table y re-suscribimos 1 vez.
                                watchdog_open_contract_intentos += 1
                                self.stderr.write(
                                    f"[TRADING] Timeout sin updates de open_contract. Re-suscribiendo + profit_table. "
                                    f"contract_id={int(contrato_abierto_id)} intento={watchdog_open_contract_intentos}"
                                )
                                try:
                                    await cliente.enviar(
                                        {"proposal_open_contract": 1, "contract_id": int(contrato_abierto_id), "subscribe": 1}
                                    )
                                    await cliente.enviar(
                                        {
                                            "profit_table": 1,
                                            "description": 1,
                                            "limit": int(settings.DERIV_HISTORIAL_LIMIT),
                                        }
                                    )
                                    ultimo_open_contract = time.monotonic()
                                except Exception as e:
                                    self.stderr.write(f"[TRADING] Falló watchdog open_contract: {e}")

                                # Último recurso: si tras varios intentos no hay updates, liberar para no quedar muerto días.
                                if watchdog_open_contract_intentos >= 3:
                                    self.stderr.write(
                                        f"[TRADING] FORZANDO liberación de contrato por falta de updates. contract_id={int(contrato_abierto_id)}"
                                    )
                                    contrato_abierto_id = None
                                    watchdog_open_contract_intentos = 0

                        # PESOS ACTUALES (HOY FIJOS; MAÑANA IA)
                        w = gestor_pesos.obtener_pesos_desde_ia(x)

                        # ===== UMBRAL DINÁMICO (ONLINE) OPCIONAL =====
                        umbral_compra = float(settings.UMBRAL_COMPRA)
                        umbral_venta = float(settings.UMBRAL_VENTA)
                        if adaptativo is not None:
                            u = float(adaptativo.umbral_actual())
                            if u != float("inf") and u > 0.0:
                                umbral_compra = float(u)
                                umbral_venta = -float(u)
                            else:
                                modo = str(getattr(settings, "ADAPTATIVO_MODO_SIN_EVIDENCIA", "no_operar")).strip().lower()
                                if modo == "warmup":
                                    uw = float(getattr(settings, "ADAPTATIVO_UMBRAL_WARMUP", 0.09))
                                    umbral_compra = float(abs(uw))
                                    umbral_venta = -float(abs(uw))
                                else:
                                    # Sin evidencia suficiente => no operar.
                                    umbral_compra = float("inf")
                                    umbral_venta = -float("inf")

                        resultado = evaluar_senal(
                            vector_mercado=x_eval,
                            vector_pesos=w,
                            umbral_compra=umbral_compra,
                            umbral_venta=umbral_venta,
                            devolver_contribuciones=True,
                            top_n=int(settings.SENAL_TOP_N),
                        )

                        # CALENTAMIENTO: EVITA OPERAR CON ESTADÍSTICAS INESTABLES.
                        if not constructor.listo_para_operar():
                            # MANTENER CONTRIBUCIONES PARA DEBUG AUNQUE NO SE OPERE.
                            resultado = type(resultado)(
                                valor=resultado.valor,
                                decision="NO_OPERAR",
                                contribuciones=resultado.contribuciones,
                            )

                        # ===== TELEMETRÍA DE SEÑAL (PARA AUDITORÍA Y DASHBOARD) =====
                        top_contrib = []
                        if resultado.contribuciones:
                            for nombre, contrib in resultado.contribuciones:
                                top_contrib.append(
                                    {
                                        "variable": str(nombre),
                                        "contribucion": float(contrib),
                                        "x": float(x_eval.get(nombre, 0.0)),
                                        "w": float(w.get(nombre, 0.0)),
                                    }
                                )

                        # ACTUALIZACIÓN "SUAVE" PARA DASHBOARD (NO ESCRIBIR EN CADA TICK).
                        # INCLUYE: ÚLTIMO TICK + TELEMETRÍA DE SEÑAL (w^T x).
                        ahora = time.monotonic()
                        if (ahora - ultimo_persist) >= 1.0:
                            ultimo_persist = ahora
                            await sync_to_async(
                                lambda: Cuenta.objects.filter(id=cuenta.id).update(
                                    ultimo_tick_epoch=int(tick.epoch),
                                    ultimo_precio=float(tick.precio),
                                    senal_valor=float(resultado.valor),
                                    senal_decision=str(resultado.decision),
                                    senal_top_contribuciones=top_contrib,
                                ),
                                thread_sensitive=True,
                            )()

                        # HISTORIAL REAL (DERIV): PEDIR PROFIT_TABLE CADA N SEGUNDOS.
                        if modo_real:
                            ahora_h = time.monotonic()
                            if (ahora_h - ultimo_historial) >= float(settings.DERIV_HISTORIAL_CADA_SEGUNDOS):
                                ultimo_historial = ahora_h
                                await cliente.enviar(
                                    {
                                        "profit_table": 1,
                                        "description": 1,
                                        "limit": int(settings.DERIV_HISTORIAL_LIMIT),
                                    }
                                )

                        # ===== EJECUCIÓN REAL (DERIV) =====
                        if modo_real and esperando is None and contrato_abierto_id is None:
                            if resultado.decision in {"COMPRA", "VENTA"} and not gestor_riesgo.bloqueado:
                                # STAKE:
                                # - Por defecto: stake por riesgo (max_riesgo_por_operacion * capital_actual)
                                # - Opcional: DERIV_STAKE_FIJO para forzar un monto (p.ej. 0.5 USD)
                                stake_fijo = getattr(settings, "DERIV_STAKE_FIJO", None)
                                riesgo_cap = min(float(gestor_riesgo.riesgo_disponible()), float(gestor_riesgo.capital_actual))
                                min_stake = float(getattr(settings, "DERIV_MIN_STAKE", 1.0))

                                if riesgo_cap <= 0.0:
                                    continue

                                # Si el riesgo disponible no alcanza el mínimo, NO operamos (evita violar el riesgo).
                                if riesgo_cap + 1e-12 < min_stake:
                                    self.stderr.write(
                                        f"[TRADING] SKIP stake_minimo_sobre_riesgo riesgo_cap={riesgo_cap:.4f} min_stake={min_stake:.4f}"
                                    )
                                    continue

                                # Base stake: fijo (si existe) o riesgo_cap.
                                if stake_fijo is not None:
                                    try:
                                        stake = float(stake_fijo)
                                    except Exception:
                                        stake = float(riesgo_cap)
                                else:
                                    stake = float(riesgo_cap)

                                # Respetar límites de riesgo/capital y mínimo.
                                stake = min(float(stake), float(riesgo_cap))
                                stake = max(float(stake), float(min_stake))
                                if stake > 0:
                                    contract_type = "CALL" if resultado.decision == "COMPRA" else "PUT"

                                    # ===== GATING POR HORARIO (LOCAL) =====
                                    # Evita operar en ventanas malas pero permite que el proceso corra continuo 24/7.
                                    try:
                                        hora_local = self._hora_local(int(tick.epoch))
                                    except Exception:
                                        hora_local = None
                                    if hora_local is not None and hora_local in horas_bloqueadas:
                                        self.stderr.write(
                                            f"[TRADING] SKIP horario_bloqueado hora={int(hora_local):02d} decision={resultado.decision} contract_type={contract_type}"
                                        )
                                        continue

                                    # ===== GATING POR CONTRACT TYPE =====
                                    # Permite apagar CALL o restringir tipos desde .env sin cambiar lógica.
                                    if contract_type not in contract_types_permitidos:
                                        self.stderr.write(
                                            f"[TRADING] SKIP contract_type_no_permitido decision={resultado.decision} contract_type={contract_type}"
                                        )
                                        continue

                                    dur = int(settings.DERIV_DURACION_TICKS)
                                    dur_max = int(getattr(settings, "DERIV_MAX_DURACION_TICKS", 10))
                                    if dur_max > 0 and dur > dur_max:
                                        ahora_w = time.monotonic()
                                        if (ahora_w - ultimo_warn_duracion) >= 5.0:
                                            ultimo_warn_duracion = ahora_w
                                            self.stderr.write(
                                                f"[TRADING] duration inválida para Deriv: DERIV_DURACION_TICKS={dur} "
                                                f"(máximo configurado={dur_max}). Ajusta .env o el mercado. No se enviará proposal."
                                            )
                                        continue
                                    self.stderr.write(
                                        f"[TRADING] señal={resultado.decision} s={float(resultado.valor):+.4f} stake={float(stake):.2f} "
                                        f"dur={dur} contract_type={contract_type}"
                                    )
                                    await cliente.enviar(
                                        {
                                            "proposal": 1,
                                            "amount": float(stake),
                                            "basis": "stake",
                                            "contract_type": contract_type,
                                            "currency": (balance_moneda or "USD"),
                                            "duration": dur,
                                            "duration_unit": "t",
                                            "symbol": symbol,
                                        }
                                    )
                                    esperando = {
                                        "tipo": "proposal",
                                        "stake": float(stake),
                                        "senal_valor": float(resultado.valor),
                                        "umbral_usado": float(abs(umbral_compra)) if umbral_compra != float("inf") else None,
                                        "pesos_usados": dict(w),
                                        "senal_top_contribuciones": top_contrib,
                                    }
                                    esperando_desde = time.monotonic()

                        # ===== LOG DE ALTA SEÑAL (SIEMPRE, INCLUSO EN MODO REAL) =====
                        ahora_l = time.monotonic()
                        if (ahora_l - ultimo_log) >= 1.0 or resultado.decision in {"COMPRA", "VENTA"}:
                            ultimo_log = ahora_l
                            top_txt = ""
                            if top_contrib:
                                top_txt = " top=" + ",".join(
                                    f"{it['variable']}:{it['contribucion']:+.3f}" for it in top_contrib[:3]
                                )
                            self.stdout.write(
                                f"t={tick.epoch} p={tick.precio:.5f} s={resultado.valor:.4f} dec={resultado.decision} "
                                f"cap={gestor_riesgo.capital_actual:.2f} bloqueado={gestor_riesgo.bloqueado} "
                                f"n={ticks_procesados}{top_txt}"
                            )

                        # ===== PAPER TRADING (DESACTIVADO EN MODO REAL) =====
                        if modo_real:
                            # EN MODO REAL NO SIMULAMOS POSICIONES INTERNAS (EVITA BLOQUEO POR "PAPER" Y CONFUSIÓN DE UI).
                            continue

                        # ===== PAPER TRADING + RIESGO (SÓLO PARA DEMOSTRAR GOBERNANZA) =====
                        # STOP DISTANCIA BASADA EN VOLATILIDAD LOCAL (PROPORCIONAL AL PRECIO).
                        vol = float(x.get("volatilidad_local", 0.0))
                        stop_min = float(settings.STOP_MIN_PORCENTAJE) * float(tick.precio)
                        stop_dist = max(stop_min, 2.0 * vol * tick.precio)  # 2-sigma aproximado (simplificado)

                        # ACTUALIZAR EQUITY POR POSICIÓN ABIERTA (MARK-TO-MARKET SIMPLE CON STOP/TP).
                        if posicion is not None:
                            pnl = self._pnl_actual(posicion, tick.precio)
                            capital_mtm = gestor_riesgo.capital_actual + pnl
                            gestor_riesgo.registrar_equity(capital_mtm)

                            # SALIDAS: STOP (1R) O TP (2R) SOBRE DISTANCIA STOP.
                            if self._debe_cerrar(posicion, tick.precio):
                                gestor_riesgo.capital_actual = float(capital_mtm)

                                # CIERRE PERSISTENTE DE LA OPERACIÓN
                                if operacion_abierta is not None:
                                    motivo = self._motivo_cierre(operacion_abierta, float(tick.precio))
                                    await sync_to_async(
                                        lambda: self._db_cerrar_operacion_y_actualizar_cuenta(
                                            operacion_id=int(operacion_abierta.id),
                                            cuenta_id=int(cuenta.id),
                                            precio_salida=float(tick.precio),
                                            pnl=float(pnl),
                                            motivo=motivo,
                                            closed_epoch=int(tick.epoch),
                                            capital_actual=float(gestor_riesgo.capital_actual),
                                            max_capital_historico=float(gestor_riesgo.max_capital_historico),
                                            bloqueado=bool(gestor_riesgo.bloqueado),
                                        ),
                                        thread_sensitive=True,
                                    )()
                                    operacion_abierta = None
                                posicion = None

                        # ENTRADAS: SOLO SI NO HAY POSICIÓN ABIERTA
                        if posicion is None and resultado.decision in {"COMPRA", "VENTA"}:
                            decision_riesgo = gestor_riesgo.autorizar_operacion(distancia_stop=stop_dist)
                            if decision_riesgo.permitido:
                                direccion = "LARGO" if resultado.decision == "COMPRA" else "CORTO"
                                operacion_abierta = await sync_to_async(
                                    lambda: Operacion.objects.create(
                                        cuenta_id=int(cuenta.id),
                                        simbolo=symbol,
                                        estado=Operacion.Estado.ABIERTA,
                                        direccion=direccion,
                                        precio_entrada=float(tick.precio),
                                        tamanio=float(decision_riesgo.tamanio_posicion),
                                        stop_distancia=float(stop_dist),
                                        opened_epoch=int(tick.epoch),
                                    ),
                                    thread_sensitive=True,
                                )()
                                posicion = PosicionPaper(
                                    direccion=direccion,
                                    precio_entrada=float(tick.precio),
                                    tamanio=float(decision_riesgo.tamanio_posicion),
                                    stop_distancia=float(stop_dist),
                                    operacion_id=int(operacion_abierta.id),
                                )

                        # ACTUALIZAR CUENTA (MTM) DE FORMA LIMITADA PARA VISUALIZACIÓN.
                        ahora2 = time.monotonic()
                        if (ahora2 - ultimo_persist) >= 1.0:
                            ultimo_persist = ahora2
                            cap_vista = float(gestor_riesgo.capital_actual)
                            if posicion is not None:
                                cap_vista = float(gestor_riesgo.capital_actual + self._pnl_actual(posicion, tick.precio))
                            await sync_to_async(
                                lambda: Cuenta.objects.filter(id=cuenta.id).update(
                                    capital_actual=cap_vista,
                                    max_capital_historico=float(gestor_riesgo.max_capital_historico),
                                    bloqueado=bool(gestor_riesgo.bloqueado),
                                ),
                                thread_sensitive=True,
                            )()

                        # (EL LOG YA SE EMITE ARRIBA PARA REAL + PAPER)

            except asyncio.TimeoutError:
                # SI NO LLEGAN MENSAJES EN 60s, SE ASUME PROBLEMA DE RED/PROXY Y SE REINTENTA.
                self.stderr.write(self.style.WARNING("[WS] Timeout sin ticks (60s). Reintentando..."))
                # IMPORTANTE: no conservar estados de órdenes a través de reconexión (evita quedar pegado).
                esperando = None
                esperando_desde = 0.0
                await dormir_segundos(3.0)
                continue
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"[WS] Error: {e}. Reintentando en 3s..."))
                # IMPORTANTE: no conservar estados de órdenes a través de reconexión (evita quedar pegado).
                esperando = None
                esperando_desde = 0.0
                await dormir_segundos(3.0)
                continue

    @staticmethod
    def _pnl_actual(posicion: PosicionPaper, precio_actual: float) -> float:
        """
        CALCULA PNL ACTUAL DE LA POSICIÓN (PAPER) EN UNIDADES MONETARIAS SIMPLIFICADAS.
        """
        if posicion.direccion == "LARGO":
            return (precio_actual - posicion.precio_entrada) * posicion.tamanio
        return (posicion.precio_entrada - precio_actual) * posicion.tamanio

    @staticmethod
    def _debe_cerrar(posicion: PosicionPaper, precio_actual: float) -> bool:
        """
        REGLA DE SALIDA SIMPLE:
        - STOP: -1R
        - TP: +2R
        """
        if posicion.direccion == "LARGO":
            stop = posicion.precio_entrada - posicion.stop_distancia
            tp = posicion.precio_entrada + (2.0 * posicion.stop_distancia)
            return (precio_actual <= stop) or (precio_actual >= tp)

        stop = posicion.precio_entrada + posicion.stop_distancia
        tp = posicion.precio_entrada - (2.0 * posicion.stop_distancia)
        return (precio_actual >= stop) or (precio_actual <= tp)

    @staticmethod
    def _en_entorno_virtual() -> bool:
        """
        DETECTA SI SE ESTÁ EJECUTANDO EN UN ENTORNO VIRTUAL.
        """
        base = getattr(sys, "base_prefix", sys.prefix)
        return bool(sys.prefix != base)

    @staticmethod
    def _motivo_cierre(op: Operacion, precio_actual: float) -> str:
        """
        CLASIFICA EL MOTIVO DE CIERRE (STOP/TP) PARA AUDITORÍA.
        """
        entrada = float(op.precio_entrada)
        d = float(op.stop_distancia)
        if op.direccion == Operacion.Direccion.LARGO:
            if precio_actual <= (entrada - d):
                return "STOP"
            if precio_actual >= (entrada + 2.0 * d):
                return "TP"
        else:
            if precio_actual >= (entrada + d):
                return "STOP"
            if precio_actual <= (entrada - 2.0 * d):
                return "TP"
        return "CIERRE"

    @staticmethod
    def _obtener_o_crear_cuenta(*, simbolo: str, gestor_riesgo: GestorRiesgo) -> Cuenta:
        """
        CREA O RECUPERA LA CUENTA PERSISTENTE PARA EL DASHBOARD.

        REGLA:
        - SI YA EXISTE, SE REANUDA CON SU CAPITAL (EVITA RESETEAR AL REINICIAR EL BOT).
        """
        cuenta = Cuenta.objects.filter(simbolo=simbolo).order_by("-updated_at").first()
        if cuenta is None:
            cuenta = Cuenta.objects.create(
                simbolo=simbolo,
                capital_inicial=float(settings.CAPITAL_INICIAL),
                capital_actual=float(settings.CAPITAL_INICIAL),
                max_capital_historico=float(settings.CAPITAL_INICIAL),
                bloqueado=False,
            )

        # REANUDAR ESTADO DE RIESGO DESDE BD
        gestor_riesgo.capital_actual = float(cuenta.capital_actual)
        gestor_riesgo.max_capital_historico = float(cuenta.max_capital_historico)
        gestor_riesgo.bloqueado = bool(cuenta.bloqueado)
        return cuenta

    @staticmethod
    def _db_cerrar_operacion_y_actualizar_cuenta(
        *,
        operacion_id: int,
        cuenta_id: int,
        precio_salida: float,
        pnl: float,
        motivo: str,
        closed_epoch: int,
        capital_actual: float,
        max_capital_historico: float,
        bloqueado: bool,
    ) -> None:
        """
        CIERRA OPERACIÓN Y ACTUALIZA CUENTA EN UNA TRANSACCIÓN (CONSISTENCIA).
        """
        with transaction.atomic():
            Operacion.objects.filter(id=operacion_id).update(
                estado=Operacion.Estado.CERRADA,
                precio_salida=float(precio_salida),
                pnl_realizado=float(pnl),
                motivo_cierre=str(motivo),
                closed_epoch=int(closed_epoch),
            )
            Cuenta.objects.filter(id=cuenta_id).update(
                capital_actual=float(capital_actual),
                max_capital_historico=float(max_capital_historico),
                bloqueado=bool(bloqueado),
            )

    @staticmethod
    def _db_registrar_compra_deriv(
        *,
        cuenta_id: int,
        simbolo: str,
        contract_id: int,
        transaction_id: int | None,
        buy_price: float,
        moneda: str,
        senal_valor: float | None = None,
        umbral_usado: float | None = None,
        pesos_usados: dict | None = None,
        senal_top_contribuciones: list | None = None,
    ) -> None:
        OperacionDeriv.objects.update_or_create(
            contract_id=int(contract_id),
            defaults={
                "cuenta_id": int(cuenta_id),
                "simbolo": str(simbolo),
                "transaction_id": int(transaction_id) if transaction_id is not None else None,
                "estado": OperacionDeriv.Estado.ABIERTA,
                "creada_por_bot": True,
                "buy_price": float(buy_price) if buy_price else None,
                "moneda": str(moneda or ""),
                "senal_valor": float(senal_valor) if senal_valor is not None else None,
                "umbral_usado": float(umbral_usado) if umbral_usado is not None else None,
                "pesos_usados": pesos_usados,
                "senal_top_contribuciones": senal_top_contribuciones,
            },
        )

    async def _procesar_profit_table(self, *, cuenta_id: int, raw: dict) -> None:
        """
        INGESTA HISTORIAL REAL DESDE `profit_table`.
        """
        tabla = raw.get("profit_table") or {}
        trans = tabla.get("transactions") or []

        def _actualizar_solo_existentes() -> None:
            # REGLA: NO IMPORTAR HISTÓRICO COMPLETO DE DERIV.
            # SOLO ACTUALIZAR OPERACIONES YA CREADAS POR ESTE BOT (ENTRADAS REALES).
            existentes = set(
                OperacionDeriv.objects.filter(cuenta_id=int(cuenta_id), creada_por_bot=True).values_list(
                    "contract_id", flat=True
                )
            )
            for t in trans:
                cid = t.get("contract_id")
                if cid is None:
                    continue
                cid_i = int(cid)
                if cid_i not in existentes:
                    continue
                buy_price = float(t.get("buy_price")) if t.get("buy_price") is not None else None
                sell_price = float(t.get("sell_price")) if t.get("sell_price") is not None else None
                profit = float(t.get("profit")) if t.get("profit") is not None else None
                if profit is None and buy_price is not None and sell_price is not None:
                    # SI DERIV NO ENVÍA PROFIT EXPLÍCITO, SE DERIVA COMO SELL - BUY.
                    profit = float(sell_price) - float(buy_price)

                moneda = str(t.get("currency") or "")
                if not moneda:
                    moneda = str(Cuenta.objects.filter(id=int(cuenta_id)).values_list("moneda_deriv", flat=True).first() or "")

                OperacionDeriv.objects.filter(contract_id=cid_i).update(
                    simbolo=str(t.get("symbol") or ""),
                    transaction_id=int(t["transaction_id"]) if t.get("transaction_id") is not None else None,
                    contract_type=str(t.get("contract_type") or ""),
                    longcode=str(t.get("longcode") or ""),
                    shortcode=str(t.get("shortcode") or ""),
                    estado=OperacionDeriv.Estado.CERRADA if t.get("sell_time") else OperacionDeriv.Estado.ABIERTA,
                    moneda=moneda,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    payout=float(t.get("payout")) if t.get("payout") is not None else None,
                    profit=profit,
                    opened_epoch=int(t.get("purchase_time")) if t.get("purchase_time") is not None else None,
                    closed_epoch=int(t.get("sell_time")) if t.get("sell_time") is not None else None,
                )

        await sync_to_async(_actualizar_solo_existentes, thread_sensitive=True)()

    async def _procesar_open_contract(self, *, cuenta_id: int, simbolo: str, contrato: dict) -> None:
        """
        ACTUALIZA LA OPERACIÓN ABIERTA DESDE `proposal_open_contract`.
        """
        cid = contrato.get("contract_id")
        if cid is None:
            return

        def _upsert() -> None:
            buy_price = float(contrato.get("buy_price")) if contrato.get("buy_price") is not None else None
            sell_price = float(contrato.get("sell_price")) if contrato.get("sell_price") is not None else None
            profit = float(contrato.get("profit")) if contrato.get("profit") is not None else None
            if profit is None and buy_price is not None and sell_price is not None:
                profit = float(sell_price) - float(buy_price)

            moneda = str(contrato.get("currency") or "")
            if not moneda:
                moneda = str(Cuenta.objects.filter(id=int(cuenta_id)).values_list("moneda_deriv", flat=True).first() or "")

            OperacionDeriv.objects.update_or_create(
                contract_id=int(cid),
                defaults={
                    "cuenta_id": int(cuenta_id),
                    "simbolo": str(simbolo),
                    "contract_type": str(contrato.get("contract_type") or ""),
                    "longcode": str(contrato.get("longcode") or ""),
                    "shortcode": str(contrato.get("shortcode") or ""),
                    "estado": OperacionDeriv.Estado.CERRADA if int(contrato.get("is_sold", 0)) == 1 else OperacionDeriv.Estado.ABIERTA,
                    "moneda": moneda,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "payout": float(contrato.get("payout")) if contrato.get("payout") is not None else None,
                    "profit": profit,
                    "opened_epoch": int(contrato.get("date_start")) if contrato.get("date_start") is not None else None,
                    "closed_epoch": int(contrato.get("sell_time")) if contrato.get("sell_time") is not None else None,
                },
            )

        await sync_to_async(_upsert, thread_sensitive=True)()


