from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import pickle
import math
from pathlib import Path
import numpy as np
from datetime import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from gestion_riesgo.gestor_riesgo import GestorRiesgo
from gestion_riesgo.models import BalanceDerivSnapshot, Cuenta, Operacion, OperacionDeriv, TickDerivHistorico, TickDerivSnapshot
from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS, dormir_segundos, obtener_duraciones_disponibles
from vector_pesos.senal_spp import EstadoSPP, ResultadoSenalSPP, evaluar_senal_spp

# Importar estrategia Momentum Breakout
try:
    from estrategia_momentum import EstadoMomentum, evaluar_momentum_breakout, reportar_resulto
    from estrategia_config import MOMENTUM_PARAMS, RISK_PARAMS, SYMBOL_CONFIG
    MOMENTUM_AVAILABLE = True
except ImportError:
    MOMENTUM_AVAILABLE = False


def _ema(series, span):
    if len(series) == 0:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [series[0]]
    for x in series[1:]:
        out.append(alpha * x + (1 - alpha) * out[-1])
    return out


def _features_from_precios(precios: list[float], epoch_actual: int | None = None) -> dict | None:
    """
    Calcula features ligeras (mismas que el entrenamiento LightGBM).
    Requiere al menos 200 puntos para tener ema200 estable.
    """
    if not precios or len(precios) < 220:
        return None
    xs = list(precios)
    ema50 = _ema(xs, 50)
    ema100 = _ema(xs, 100)
    ema200 = _ema(xs, 200)
    price = xs
    gap = [a - b for a, b in zip(ema50, ema100)]
    slope50_10 = []
    for i in range(len(ema50)):
        prev = ema50[i - 10] if i >= 10 else ema50[0]
        slope50_10.append(ema50[i] - prev)
    returns = [0.0]
    for i in range(1, len(price)):
        returns.append(price[i] - price[i - 1])
    ret_std_50 = []
    for i in range(len(price)):
        win = returns[max(0, i - 49) : i + 1]
        if len(win) == 0:
            ret_std_50.append(0.0)
        else:
            m = sum(win) / len(win)
            var = sum((r - m) ** 2 for r in win) / len(win)
            ret_std_50.append(math.sqrt(var))
    z_price_ema50 = []
    for p, e50, s in zip(price, ema50, ret_std_50):
        z_price_ema50.append((p - e50) / (s + 1e-8))

    sign_rel = [1 if (p - e50) >= 0 else -1 for p, e50 in zip(price, ema50)]
    flips = [0]
    for i in range(1, len(sign_rel)):
        flips.append(1 if sign_rel[i] != sign_rel[i - 1] else 0)
    flips40 = []
    for i in range(len(flips)):
        win = flips[max(0, i - 39) : i + 1]
        flips40.append(sum(win))

    feats = {
        "price": price[-1],
        "ema50": ema50[-1],
        "ema100": ema100[-1],
        "ema200": ema200[-1],
        "gap": gap[-1],
        "gap_rel": gap[-1] / (abs(ema100[-1]) + 1e-6),
        "slope50_10": slope50_10[-1],
        "ret1": price[-1] - price[-2],
        "ret5": price[-1] - price[-6] if len(price) > 6 else price[-1] - price[0],
        "ret20": price[-1] - price[-21] if len(price) > 21 else price[-1] - price[0],
        "ret_std_50": ret_std_50[-1],
        "z_price_ema50": z_price_ema50[-1],
        "flips40": flips40[-1],
    }
    # Hora del día (si tenemos epoch)
    if epoch_actual:
        try:
            h = datetime.utcfromtimestamp(int(epoch_actual)).hour
            feats["hour_sin"] = math.sin(2 * math.pi * h / 24.0)
            feats["hour_cos"] = math.cos(2 * math.pi * h / 24.0)
        except Exception:
            feats["hour_sin"] = 0.0
            feats["hour_cos"] = 0.0
    else:
        feats["hour_sin"] = 0.0
        feats["hour_cos"] = 0.0
    return feats


class LightGBMPredictor:
    def __init__(self):
        self.models: dict[str, dict] = {}

    def load_from_env(self):
        for sym, env_key in (("R_10", "LGBM_MODEL_R10"), ("R_100", "LGBM_MODEL_R100")):
            path = str(getattr(settings, env_key, "") or "").strip()
            if not path:
                continue
            p = Path(path)
            if not p.exists():
                _append_runtime_log(f"[ML] Modelo {env_key} no encontrado en {p}")
                continue
            try:
                with open(p, "rb") as f:
                    artifact = pickle.load(f)
                if not isinstance(artifact, dict) or "model" not in artifact or "threshold" not in artifact:
                    _append_runtime_log(f"[ML] Modelo {env_key} inválido: falta model/threshold")
                    continue
                self.models[sym] = artifact
                _append_runtime_log(f"[ML] Modelo {env_key} cargado (thr={artifact.get('threshold')})")
            except Exception as e:
                _append_runtime_log(f"[ML] Error cargando {env_key}: {e}")

    def predict(self, sym: str, feats: dict) -> tuple[float, float] | None:
        art = self.models.get(sym)
        if not art:
            return None
        model = art.get("model")
        thr = float(art.get("threshold", 0.5))
        try:
            X = np.array([[feats.get(k, 0.0) for k in art.get("meta", {}).get("features", [])]], dtype=float)
            prob = float(model.predict_proba(X)[0, 1])
            return prob, thr
        except Exception as e:
            _append_runtime_log(f"[ML] predict error {sym}: {e}")
            return None

def _runtime_log_path() -> str:
    """
    Archivo "tail-friendly" para el dashboard (panel de logs).
    """
    # Prioridad: settings -> env -> default dentro del proyecto
    try:
        from django.conf import settings as _settings  # local import (evita problemas en import-time)

        p = str(getattr(_settings, "BOT_RUNTIME_LOG_FILE", "") or "").strip()
    except Exception as e:
        import logging
        logging.warning(f"Could not load Django settings: {e}")
    if not p:
        p = str(os.environ.get("BOT_RUNTIME_LOG_FILE", "") or "").strip()
    if not p:
        p = os.path.join(os.getcwd(), "logs", "runtime.log")
    return p


def _append_runtime_log(line: str) -> None:
    """
    Anexa una línea a un archivo de log local para poder verla en el dashboard.
    Diseñado para ser ultra-resistente (nunca debe tumbar el bot).
    """
    try:
        p = _runtime_log_path()
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)

        # Rotación ultra-simple por tamaño (evita crecimiento infinito).
        # Mantiene solo ~2MB finales si supera ~10MB.
        try:
            if os.path.exists(p) and os.path.getsize(p) > (10 * 1024 * 1024):
                with open(p, "rb") as rf:
                    rf.seek(0, os.SEEK_END)
                    end = rf.tell()
                    keep = 2 * 1024 * 1024
                    start = max(0, end - keep)
                    rf.seek(start, os.SEEK_SET)
                    data = rf.read()
                with open(p, "wb") as wf:
                    wf.write(data)
                    if not data.endswith(b"\n"):
                        wf.write(b"\n")
        except Exception as e:
            import logging
            logging.warning(f"Runtime log rotation failed: {e}")

        s = str(line or "")
        if not s.endswith("\n"):
            s += "\n"
        with open(p, "a", encoding="utf-8", errors="replace") as f:
            f.write(s)
    except Exception as e:
        import logging
        logging.warning(f"Runtime log write failed: {e}")


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
    help = "Consume ticks de Deriv y ejecuta estrategia SPP (estructura + pendiente + pullback) por símbolo."

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
        # Obtener símbolos: si se especifica --symbol, usar ese; si no, usar R_10 y R_100 por defecto
        symbol_arg = options.get("symbol")
        if symbol_arg:
            symbols = [symbol_arg.strip()]
        else:
            # Por defecto, manejar ambos activos
            symbols = ["R_10", "R_100"]
        
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

        # Cargar modelos ML (opcional)
        self.ml = LightGBMPredictor()
        self.ml.load_from_env()
        
        # Ejecutar para todos los símbolos en paralelo
        asyncio.run(
            self._run_multiple_symbols(
                symbols=symbols,
                max_ticks=max_ticks,
                max_segundos=max_segundos,
                max_reintentos=max_reintentos,
                ilimitado=ilimitado,
                ejecutar_real=ejecutar_real,
            )
        )

    async def _run_multiple_symbols(
        self,
        symbols: list[str],
        *,
        max_ticks: int,
        max_segundos: int,
        max_reintentos: int,
        ilimitado: bool,
        ejecutar_real: bool = False,
    ) -> None:
        """
        Ejecuta el bot para múltiples símbolos en paralelo.
        """
        # Crear tareas para cada símbolo
        tasks = []
        for symbol in symbols:
            task = self._run(
                symbol=symbol,
                max_ticks=max_ticks,
                max_segundos=max_segundos,
                max_reintentos=max_reintentos,
                ilimitado=ilimitado,
                ejecutar_real=ejecutar_real,
            )
            tasks.append(task)
        
        # Ejecutar todas las tareas en paralelo
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # No ocultar errores: si no, systemd entra en loop y nunca se entiende el motivo.
        for sym, res in zip(symbols, results):
            if isinstance(res, Exception):
                msg = f"[{sym}] [FATAL] Stream terminó con error: {res!r}"
                try:
                    self.stderr.write(msg)
                except Exception:
                    pass
                _append_runtime_log(msg)

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
        # ===== ESTRATEGIA: ESTRUCTURA + PENDIENTE + PULLBACK (SPP) =====
        # Requerimiento: NO usar máximos/mínimos (extremos) ni cruces simples.
        # EMAs fijas: 50 (rápida) y 100 (lenta).
        estrategia_tipo = str(getattr(settings, "ESTRATEGIA_TIPO", "spp") or "spp").strip().lower()
        if estrategia_tipo in {"extremos", "vector", "vectores", "wtx"}:
            # Backward-compat: forzamos a la nueva estrategia.
            estrategia_tipo = "spp"
        
        # Inicializar estado según estrategia
        self.stdout.write(f"[BOOT] Estrategia tipo: {estrategia_tipo}, MOMENTUM_AVAILABLE: {MOMENTUM_AVAILABLE}")
        if estrategia_tipo == "momentum" and MOMENTUM_AVAILABLE:
            estado_momentum = EstadoMomentum()
            self.stdout.write(self.style.SUCCESS(f"[BOOT] Usando estrategia Momentum Breakout"))
        else:
            estado_momentum = None
            if estrategia_tipo == "momentum":
                self.stdout.write(self.style.WARNING(f"[BOOT] Momentum no disponible, usando SPP"))
            estrategia_tipo = "spp"  # Fallback a SPP
        
        estado_spp = EstadoSPP()

        gestor_riesgo = GestorRiesgo(
            capital_inicial=settings.CAPITAL_INICIAL,
            max_riesgo_por_operacion=settings.MAX_RIESGO_POR_OPERACION,
            max_drawdown=settings.MAX_DRAWDOWN,
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

        # ===== MEMORIA LOCAL (ANTI "PAUSA EXPIRADA") =====
        # Guardamos el último estado conocido para poder corregir bloqueos temporales
        # incluso si Deriv no emite eventos de balance por un tiempo.
        ciclo_pausa_hasta_epoch_mem: int | None = int(cuenta.ciclo_pausa_hasta_epoch) if getattr(cuenta, "ciclo_pausa_hasta_epoch", None) else None
        balance_deriv_mem: float = float(getattr(cuenta, "balance_deriv", 0.0) or 0.0)
        max_balance_deriv_mem: float = float(getattr(cuenta, "max_balance_deriv_historico", 0.0) or 0.0)
        riesgo_motivo_mem: str = str(getattr(cuenta, "riesgo_motivo", "") or "")

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

        # ===== CONTEXTO DE ARRANQUE (DB/CUENTA/HORA) =====
        # Log de inicio para identificar qué símbolo está procesando
        print(f"[{symbol}] Iniciando bot para símbolo {symbol}")
        _append_runtime_log(f"[{symbol}] Iniciando bot para símbolo {symbol}")
        try:
            db_name = settings.DATABASES.get("default", {}).get("NAME", "<desconocido>")
        except Exception:
            db_name = "<desconocido>"
        ahora_epoch = int(time.time())
        try:
            hora_local_now = int(self._hora_local(ahora_epoch))
        except Exception:
            hora_local_now = -1
        _cfg_line = (
            "[CFG] "
            f"db={db_name} cuenta_id={int(cuenta.id)} "
            f"hora_local={hora_local_now} horas_bloqueadas={sorted(list(horas_bloqueadas))}"
        )
        self.stdout.write(_cfg_line)
        _append_runtime_log(f"[{symbol}] {_cfg_line}")

        # ===== AUTO-INICIALIZAR CICLO SI FALTA (modo real) =====
        # Si Deriv no emite updates de balance por un rato, `ciclo_balance_inicio` puede quedarse en None.
        # Lo inicializamos al arrancar usando el balance_deriv persistido (si existe).
        if modo_real and bool(getattr(settings, "CICLO_HABILITADO", False)):
            try:
                if getattr(cuenta, "ciclo_balance_inicio", None) is None and getattr(cuenta, "balance_deriv", None) is not None:
                    from django.utils import timezone as django_timezone

                    baseline = float(cuenta.balance_deriv)
                    await sync_to_async(
                        lambda: Cuenta.objects.filter(id=cuenta.id).update(
                            ciclo_balance_inicio=baseline,
                            ciclo_inicio_epoch=int(ahora_epoch),
                            ciclo_pausa_hasta_epoch=None,
                            ciclo_ultimo_evento="CICLO_INICIADO_AUTO",
                            riesgo_motivo="CICLO_ACTIVO",
                            updated_at=django_timezone.now(),
                        ),
                        thread_sensitive=True,
                    )()
                    # Refrescar copia local (para que el resto del loop vea el baseline).
                    cuenta = await sync_to_async(lambda: Cuenta.objects.get(id=cuenta.id), thread_sensitive=True)()
            except Exception as e:
                self.stderr.write(f"[CFG] WARN no se pudo auto-inicializar ciclo: {e}")

        # ===== CONFIG EFECTIVA (LOG 1 VEZ) =====
        # Nota: stdout sin style para que quede grepeable en `journalctl | grep`.
        stake_fijo_cfg = getattr(settings, "DERIV_STAKE_FIJO", None)
        ema_fast_cfg = int(getattr(settings, "SPP_EMA_FAST", 9))
        ema_slow_cfg = int(getattr(settings, "SPP_EMA_SLOW", 21))
        _cfg_line2 = (
            "[CFG] "
            f"modo_real={modo_real} symbol={symbol} "
            f"estrategia={estrategia_tipo} "
            f"ema_fast={ema_fast_cfg} ema_slow={ema_slow_cfg} "
            f"slope_n={int(getattr(settings,'SPP_SLOPE_N',5) or 5)} "
            f"balance_poll_cada_seg={balance_poll_cada_seg:.0f} "
            f"min_stake={float(getattr(settings,'DERIV_MIN_STAKE',0.35))} "
            f"stake_fijo={float(stake_fijo_cfg) if stake_fijo_cfg is not None else '-'} "
            f"contract_types={','.join(sorted(contract_types_permitidos))} "
            f"horas_bloqueadas={','.join(str(h) for h in sorted(horas_bloqueadas)) if horas_bloqueadas else '-'} "
        )
        self.stdout.write(_cfg_line2)
        _append_runtime_log(f"[{symbol}] {_cfg_line2}")

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

            _ws_line = f"[{symbol}] [WS] Conectando a Deriv | intento={intentos} | symbol={symbol} | app_id={settings.DERIV_APP_ID}"
            self.stdout.write(self.style.SUCCESS(_ws_line))
            _append_runtime_log(_ws_line)
            try:
                async with ClienteDerivWS(token=settings.DERIV_API_TOKEN) as cliente:
                    # BALANCE REAL SOLO SI HAY TOKEN (AUTORIZACIÓN).
                    incluir_balance = bool(settings.DERIV_API_TOKEN)
                    if incluir_balance:
                        _ws_line2 = f"[{symbol}] [WS] Suscrito (ticks + balance). Esperando eventos..."
                        self.stdout.write(self.style.SUCCESS(_ws_line2))
                        _append_runtime_log(_ws_line2)
                    else:
                        _ws_warn = f"[{symbol}] [WS] Sin DERIV_API_TOKEN: no se puede suscribir a balance."
                        self.stderr.write(self.style.WARNING(_ws_warn))
                        _append_runtime_log(_ws_warn)
                        _ws_line3 = f"[{symbol}] [WS] Suscrito (solo ticks). Esperando ticks..."
                        self.stdout.write(self.style.SUCCESS(_ws_line3))
                        _append_runtime_log(_ws_line3)

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

                    _ws_line4 = f"[{symbol}] [WS] Conexión establecida, iniciando stream de eventos..."
                    self.stdout.write(self.style.SUCCESS(_ws_line4))
                    _append_runtime_log(_ws_line4)

                    # OBTENER DURACIONES VÁLIDAS PARA ESTE SÍMBOLO
                    # Importante: consultar siempre (demo y real) para evitar OfferingsValidationError
                    duraciones_disponibles: list[int] = []
                    try:
                        duraciones_disponibles = await obtener_duraciones_disponibles(cliente, symbol)
                        if duraciones_disponibles:
                            self.stderr.write(
                                f"[TRADING] Duraciones válidas para {symbol}: {duraciones_disponibles}"
                            )
                        else:
                            self.stderr.write(
                                f"[TRADING] No se pudieron obtener duraciones para {symbol}, usando fallback"
                            )
                    except Exception as e:
                        self.stderr.write(f"[TRADING] Error obteniendo duraciones: {e}")

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
                        
                        # ===== SNAPSHOT PERIÓDICO (independiente de eventos de balance) =====
                        ahora_s = time.monotonic()
                        cada_snapshot = float(getattr(settings, "BALANCE_SNAPSHOT_CADA_SEG", 60))
                        if cada_snapshot <= 0:
                            cada_snapshot = 60.0
                        if (ahora_s - ultimo_balance_snapshot) >= cada_snapshot:
                            ultimo_balance_snapshot = ahora_s
                            try:
                                await sync_to_async(
                                    lambda: BalanceDerivSnapshot.objects.create(
                                        cuenta_id=int(cuenta.id),
                                        balance=float(balance_deriv_mem),
                                        moneda=str(balance_moneda or "USD"),
                                        epoch=int(time.time()),
                                    ),
                                    thread_sensitive=True,
                                )()
                            except Exception:
                                pass

                        if ev.get("tipo") == "balance":
                            bal = ev["balance"]
                            # EN MODO REAL: BLOQUEO/DRAWDOWN DEBE BASARSE SOLO EN BALANCE REAL DERIV.
                            # EVITA MEZCLAR HISTÓRICOS "PAPER" CON BALANCE REAL (ESO TE BLOQUEA INJUSTAMENTE).
                            if modo_real:
                                balance_val = float(bal.balance)
                                currency = str(bal.currency or "")

                                async def _actualizar_balance_real() -> None:
                                    nonlocal ciclo_pausa_hasta_epoch_mem
                                    nonlocal balance_deriv_mem
                                    nonlocal max_balance_deriv_mem
                                    nonlocal riesgo_motivo_mem
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
                                    # ===== EDGE GUARD (OPCIONAL) =====
                                    edge_habil = bool(getattr(settings, "EDGE_GUARD_HABILITADO", True))
                                    edge_n = int(getattr(settings, "EDGE_GUARD_WINDOW_N", 200) or 200)
                                    edge_min_trades = int(getattr(settings, "EDGE_GUARD_MIN_TRADES", 60) or 60)
                                    edge_margin = float(getattr(settings, "EDGE_GUARD_MARGIN_WR", 0.015) or 0.015)
                                    edge_pausa_seg = int(getattr(settings, "EDGE_GUARD_PAUSA_SEG", 3600) or 3600)
                                    edge_min_streak = int(getattr(settings, "EDGE_GUARD_MIN_LOSS_STREAK", 5) or 5)

                                    ciclo_balance_inicio = float(prev.get("ciclo_balance_inicio")) if (prev and prev.get("ciclo_balance_inicio") is not None) else None
                                    ciclo_pausa_hasta = int(prev.get("ciclo_pausa_hasta_epoch")) if (prev and prev.get("ciclo_pausa_hasta_epoch") is not None) else None

                                    riesgo_motivo = ""
                                    ciclo_evento = ""
                                    ciclo_bloqueado = False
                                    nuevo_ciclo_balance_inicio = ciclo_balance_inicio
                                    nuevo_ciclo_inicio_epoch = int(prev.get("ciclo_inicio_epoch")) if (prev and prev.get("ciclo_inicio_epoch") is not None) else None
                                    nuevo_ciclo_pausa_hasta = ciclo_pausa_hasta

                                    # ===== EDGE PAUSE (persistida en riesgo_motivo) =====
                                    edge_bloqueado = False
                                    rm_prev = str(prev.get("riesgo_motivo") or "").strip() if prev else ""
                                    m_edge = re.match(r"^PAUSA_EDGE_HASTA_(\d+)$", rm_prev)
                                    edge_hasta_epoch = int(m_edge.group(1)) if m_edge else None
                                    if edge_hasta_epoch and ahora_epoch < int(edge_hasta_epoch):
                                        edge_bloqueado = True
                                        riesgo_motivo = f"PAUSA_EDGE_HASTA_{int(edge_hasta_epoch)}"
                                        ciclo_evento = "EDGE_GUARD_PAUSA"
                                    elif edge_hasta_epoch and ahora_epoch >= int(edge_hasta_epoch):
                                        # pausa expirada: limpiar para que pueda re-evaluar
                                        edge_hasta_epoch = None
                                        edge_bloqueado = False

                                    # Si no está ya en pausa, evaluar edge guard (circuit breaker).
                                    if edge_habil and (not edge_bloqueado):
                                        try:
                                            profits = list(
                                                OperacionDeriv.objects.filter(
                                                    cuenta_id=int(cuenta.id),
                                                    creada_por_bot=True,
                                                    estado=OperacionDeriv.Estado.CERRADA,
                                                    profit__isnull=False,
                                                )
                                                .order_by("-closed_epoch")
                                                .values_list("profit", flat=True)[: max(1, edge_n)]
                                            )
                                            profits_f = [float(p) for p in profits]
                                            if len(profits_f) >= int(edge_min_trades):
                                                wins = [p for p in profits_f if p > 0.0]
                                                losses = [-p for p in profits_f if p <= 0.0]
                                                avg_win = (sum(wins) / len(wins)) if wins else 0.0
                                                avg_loss = (sum(losses) / len(losses)) if losses else 0.0
                                                wr = (len(wins) / len(profits_f)) if profits_f else 0.0
                                                profit_total = sum(profits_f)
                                                breakeven_wr = (avg_loss / (avg_loss + avg_win)) if (avg_loss > 0 and avg_win > 0) else 1.0

                                                k = max(1, int(edge_min_streak))
                                                last_k = profits_f[:k]
                                                loss_streak = sum(1 for p in last_k if p <= 0.0)

                                                if profit_total < 0.0 and (wr + float(edge_margin)) < breakeven_wr and loss_streak >= k:
                                                    edge_hasta_epoch = int(ahora_epoch + max(0, int(edge_pausa_seg)))
                                                    edge_bloqueado = True
                                                    riesgo_motivo = f"PAUSA_EDGE_HASTA_{int(edge_hasta_epoch)}"
                                                    ciclo_evento = "EDGE_GUARD_TRIGGER"
                                                    self.stderr.write(
                                                        f"[RISK] EDGE_GUARD: wr={wr*100:.1f}% breakeven≈{breakeven_wr*100:.1f}% "
                                                        f"profit_total={profit_total:.2f} last{k}_losses={loss_streak}/{k} pausa={edge_pausa_seg}s"
                                                    )
                                                    _append_runtime_log(
                                                        f"[{symbol}] [RISK] EDGE_GUARD: wr={wr*100:.1f}% breakeven≈{breakeven_wr*100:.1f}% "
                                                        f"profit_total={profit_total:.2f} last{k}_losses={loss_streak}/{k} pausa={edge_pausa_seg}s"
                                                    )
                                        except Exception:
                                            pass

                                    # Si ciclos están deshabilitados, limpiamos cualquier pausa previa para evitar
                                    # quedar bloqueados por estado viejo en BD.
                                    if not ciclo_habil:
                                        nuevo_ciclo_pausa_hasta = None
                                        nuevo_ciclo_balance_inicio = None
                                        nuevo_ciclo_inicio_epoch = None

                                    if ciclo_habil:
                                        # Si estamos en pausa, bloquear.
                                        if ciclo_pausa_hasta is not None and ahora_epoch < ciclo_pausa_hasta:
                                            ciclo_bloqueado = True
                                            riesgo_motivo = f"PAUSA_CICLO_HASTA_{ciclo_pausa_hasta}"
                                            ciclo_evento = "PAUSA"
                                            # IMPORTANTE: Preservar el baseline durante la pausa.
                                            # Si no hay baseline (por reinicio del servicio), usar balance actual como fallback.
                                            if nuevo_ciclo_balance_inicio is None:
                                                nuevo_ciclo_balance_inicio = float(balance_val)
                                                nuevo_ciclo_inicio_epoch = int(ahora_epoch)
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
                                            # IMPORTANTE: Solo calcular PnL si tenemos un baseline válido.
                                            if nuevo_ciclo_balance_inicio is not None and nuevo_ciclo_balance_inicio > 0:
                                                pnl_pct = (float(balance_val) / float(nuevo_ciclo_balance_inicio)) - 1.0
                                                if pnl_pct >= float(ciclo_tp):
                                                    # META DEL CICLO ALCANZADA:
                                                    # - NO tocamos la lógica de entradas/senal.
                                                    # - Solo gobernanza de capital: pausar el bot (bloquear nuevas entradas)
                                                    #   por `CICLO_PAUSA_TP_SEG` y reiniciar el ciclo al reanudar.
                                                    pausa_tp_eff = int(max(0, int(pausa_tp)))
                                                    if pausa_tp_eff <= 0:
                                                        # Modo informativo: marcar meta alcanzada pero no pausar.
                                                        nuevo_ciclo_pausa_hasta = None
                                                        # Reiniciar baseline para nueva meta inmediatamente.
                                                        nuevo_ciclo_balance_inicio = float(balance_val)
                                                        nuevo_ciclo_inicio_epoch = int(ahora_epoch)
                                                        ciclo_bloqueado = False
                                                        riesgo_motivo = f"TAKE_PROFIT_{float(ciclo_tp):.4f}_SIN_PAUSA"
                                                        ciclo_evento = "TAKE_PROFIT_CONTINUAR"
                                                    else:
                                                        nuevo_ciclo_pausa_hasta = int(ahora_epoch + pausa_tp_eff)
                                                        # Mantener baseline del ciclo para auditoría/dashboard durante la pausa.
                                                        # Al reanudar (cuando expire), el código de arriba limpia baseline y arranca uno nuevo.
                                                        ciclo_bloqueado = True
                                                        riesgo_motivo = f"TAKE_PROFIT_{float(ciclo_tp):.4f}_PAUSA_{int(pausa_tp_eff)}s"
                                                        ciclo_evento = "TAKE_PROFIT"
                                                elif pnl_pct <= -float(ciclo_sl):
                                                    # Si pausa_sl <= 0 => stoploss informativo SIN pausar (operación continua).
                                                    if int(pausa_sl) <= 0:
                                                        nuevo_ciclo_pausa_hasta = None
                                                        nuevo_ciclo_balance_inicio = float(balance_val)
                                                        nuevo_ciclo_inicio_epoch = int(ahora_epoch)
                                                        ciclo_bloqueado = False
                                                        riesgo_motivo = f"STOPLOSS_{float(ciclo_sl):.4f}_SIN_PAUSA"
                                                        ciclo_evento = "STOPLOSS_CONTINUAR"
                                                    else:
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
                                    dd_cooldown_seg = int(getattr(settings, "DRAWDOWN_COOLDOWN_SEG", 3600))
                                    bloqueado_dd = False

                                    # Histéresis: si ya está bloqueado, requerimos recuperación adicional para desbloquear.
                                    # MEJORA: Si pasa el cooldown, resetear max para permitir recuperación gradual
                                    if dd_habil:
                                        if prev_bloqueado and bloqueado_dd:
                                            # Ya estaba bloqueado por DD - verificar si pasó el cooldown
                                            tiempo_bloqueado = ahora_epoch - prev.get("updated_at", 0)
                                            if tiempo_bloqueado >= dd_cooldown_seg:
                                                # Resetear max para permitir operar de nuevo (recovery gradual)
                                                nuevo_max = balance_val
                                                drawdown = 0.0
                                                bloqueado_dd = False
                                                self.stderr.write(f"[RISK] DRAWDOWN_COOLDOWN_PASSED reseteando max balance={balance_val:.2f}")
                                            else:
                                                bloqueado_dd = not (drawdown <= dd_unblock)
                                        elif prev_bloqueado:
                                            bloqueado_dd = not (drawdown <= dd_unblock)
                                        else:
                                            bloqueado_dd = bool(drawdown >= dd_max)
                                    else:
                                        bloqueado_dd = False

                                    bloqueado_real = bool(edge_bloqueado or ciclo_bloqueado or bloqueado_dd)
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

                                    from django.utils import timezone as django_timezone
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
                                            updated_at=django_timezone.now(),
                                        ),
                                        thread_sensitive=True,
                                    )()

                                    gestor_riesgo.capital_actual = balance_val
                                    gestor_riesgo.max_capital_historico = nuevo_max
                                    gestor_riesgo.bloqueado = bloqueado_real

                                    # Memoria local para auto-correcciones (ticks) si faltan eventos de balance.
                                    balance_deriv_mem = float(balance_val)
                                    max_balance_deriv_mem = float(nuevo_max)
                                    ciclo_pausa_hasta_epoch_mem = int(nuevo_ciclo_pausa_hasta) if nuevo_ciclo_pausa_hasta is not None else None
                                    riesgo_motivo_mem = str(riesgo_motivo or "")

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
                                from django.utils import timezone as django_timezone
                                await sync_to_async(
                                    lambda: Cuenta.objects.filter(id=cuenta.id).update(
                                        balance_deriv=float(bal.balance),
                                        moneda_deriv=str(bal.currency),
                                        updated_at=django_timezone.now(),
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
                                    entry_spot=float(esperando.get("entry_spot")) if esperando.get("entry_spot") is not None else None,
                                )
                            esperando = None
                            continue

                        # Verificar que el evento tiene un tick antes de procesarlo
                        if "tick" not in ev:
                            # Si no es un tick, ignorar el evento (puede ser otro tipo de mensaje)
                            continue
                        
                        tick_deriv = ev.get("tick")
                        # Validar que el tick no sea None y tenga los atributos necesarios
                        if tick_deriv is None:
                            continue
                        if not hasattr(tick_deriv, "epoch") or not hasattr(tick_deriv, "precio"):
                            continue
                        if tick_deriv.epoch is None or tick_deriv.precio is None:
                            continue
                        
                        ticks_procesados += 1
                        # Log cada 100 ticks para verificar que los ticks están llegando
                        if ticks_procesados % 100 == 0:
                            self.stdout.write(f"[TICKS] Procesados: {ticks_procesados} último_tick_epoch={tick_deriv.epoch} precio={tick_deriv.precio:.5f}")
                        if _limite_alcanzado():
                            self.stdout.write(self.style.SUCCESS("[FIN] Límite alcanzado. Cerrando conexión."))
                            return

                        # Tick actual (sin estrategias legacy)
                        tick = tick_deriv
                        
                        # Guardar tick para gráfico en tiempo real (mantener solo últimos N)
                        try:
                            precio_guardar = tick_deriv.precio
                            epoch_guardar = tick_deriv.epoch
                            ticks_window = 200  # Guardar últimos 200 ticks
                            if ticks_window < 10:
                                ticks_window = 10
                            # Crear nuevo tick
                            await sync_to_async(
                                lambda: TickDerivSnapshot.objects.create(
                                    cuenta_id=int(cuenta.id),
                                    precio=float(precio_guardar),
                                    epoch=int(epoch_guardar),
                                ),
                                thread_sensitive=True,
                            )()
                            
                            # Limpiar ticks antiguos (mantener solo últimos N) - solo cada 10 ticks para eficiencia
                            if ticks_procesados % 10 == 0:
                                todos_ids = await sync_to_async(
                                    lambda: list(
                                        TickDerivSnapshot.objects.filter(cuenta_id=cuenta.id)
                                        .order_by("-epoch")
                                        .values_list("id", flat=True)
                                    ),
                                    thread_sensitive=True,
                                )()
                                
                                if len(todos_ids) > ticks_window:
                                    ids_a_eliminar = todos_ids[ticks_window:]
                                    await sync_to_async(
                                        lambda: TickDerivSnapshot.objects.filter(id__in=ids_a_eliminar).delete(),
                                        thread_sensitive=True,
                                    )()
                        except Exception as e:
                            # Log del error pero no romper el bot
                            import traceback
                            error_msg = f"[TICKS] Error guardando tick #{ticks_procesados} precio={tick_deriv.precio:.5f} epoch={tick_deriv.epoch}: {e}\n{traceback.format_exc()}"
                            self.stderr.write(error_msg)
                            # También escribir a stdout para que aparezca en logs
                            self.stdout.write(self.style.ERROR(error_msg))

                        # ===== COLECTOR DE TICKS (HISTÓRICO) =====
                        # Guarda ticks “para investigación” por días (NO se limpia), controlado desde dashboard.
                        # Nota: usamos bulk_create por batches para no saturar SQLite.
                        if getattr(cuenta, "ticks_colector_activo", False):
                            try:
                                if not hasattr(self, "ticks_hist_buffer"):
                                    self.ticks_hist_buffer = []
                                    self.ticks_hist_last_flush = time.monotonic()

                                ticks_hist_buffer = self.ticks_hist_buffer
                                ticks_hist_last_flush = self.ticks_hist_last_flush

                                ticks_hist_buffer.append(
                                    TickDerivHistorico(
                                        cuenta_id=int(cuenta.id),
                                        precio=float(tick_deriv.precio),
                                        epoch=int(tick_deriv.epoch),
                                    )
                                )

                                flush_every = int(getattr(settings, "TICKS_HIST_FLUSH_EVERY", 25) or 25)
                                flush_secs = float(getattr(settings, "TICKS_HIST_FLUSH_SECS", 5.0) or 5.0)
                                now_m = time.monotonic()
                                if len(ticks_hist_buffer) >= flush_every or (now_m - ticks_hist_last_flush) >= flush_secs:
                                    batch = ticks_hist_buffer
                                    self.ticks_hist_buffer = []
                                    self.ticks_hist_last_flush = now_m

                                    def _flush() -> None:
                                        TickDerivHistorico.objects.bulk_create(batch, batch_size=1000)
                                        Cuenta.objects.filter(id=int(cuenta.id)).update(
                                            ticks_colector_total=F("ticks_colector_total") + int(len(batch)),
                                            ticks_colector_ultimo_epoch=int(tick_deriv.epoch),
                                        )

                                    await sync_to_async(_flush, thread_sensitive=True)()
                            except Exception:
                                # Nunca tumbar el bot por el colector.
                                pass
                        
                        # ===== PROCESAMIENTO =====
                        # La estrategia SPP se evalúa más abajo (sección “EVALUACIÓN DE SEÑAL (SPP)”).

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

                        # ===== AUTO-CORRECCIÓN: PAUSA DE CICLO EXPIRADA =====
                        # Si la pausa ya venció, limpiamos el estado aunque aún no llegue un evento `balance`.
                        # Esto evita "bugs temporales" de bloqueo cuando quieres operar continuo.
                        if modo_real and ciclo_pausa_hasta_epoch_mem is not None:
                            ahora_epoch_tick = int(time.time())
                            if ahora_epoch_tick >= int(ciclo_pausa_hasta_epoch_mem):
                                from django.utils import timezone as django_timezone
                                ciclo_pausa_hasta_epoch_mem = None
                                ciclo_habil = bool(getattr(settings, "CICLO_HABILITADO", False))
                                dd_habil = bool(getattr(settings, "DRAWDOWN_GLOBAL_HABILITADO", True))
                                bloqueado_dd = False
                                if dd_habil and max_balance_deriv_mem and max_balance_deriv_mem > 0:
                                    dd_max = float(getattr(settings, "MAX_DRAWDOWN", 0.0))
                                    dd_hyst = float(getattr(settings, "MAX_DRAWDOWN_HISTERESIS", 0.0))
                                    dd_hyst = max(0.0, min(dd_hyst, dd_max))
                                    dd_unblock = max(0.0, dd_max - dd_hyst)
                                    drawdown = 1.0 - (float(balance_deriv_mem) / float(max_balance_deriv_mem))
                                    prev_dd = (riesgo_motivo_mem or "").strip() == "DRAWDOWN"
                                    bloqueado_dd = (not (drawdown <= dd_unblock)) if prev_dd else bool(drawdown >= dd_max)

                                # BUGFIX:
                                # Antes limpiábamos solo la PAUSA pero dejábamos `ciclo_balance_inicio` antiguo en BD.
                                # Eso hace que al llegar el próximo `balance` (o poll) se re-evalúe con pnl_pct >= TP
                                # y se re-dispare TAKE_PROFIT => pausa 24h en loop.
                                # Aquí reiniciamos el ciclo de forma idempotente al expirar la pausa.
                                nuevo_ciclo_balance_inicio = float(balance_deriv_mem) if (ciclo_habil and float(balance_deriv_mem) > 0.0) else None
                                nuevo_ciclo_inicio_epoch = int(ahora_epoch_tick) if ciclo_habil else None

                                gestor_riesgo.bloqueado = bool(bloqueado_dd)
                                if bloqueado_dd:
                                    riesgo_motivo_mem = "DRAWDOWN"
                                else:
                                    riesgo_motivo_mem = "CICLO_ACTIVO" if ciclo_habil else "OK"
                                await sync_to_async(
                                    lambda: Cuenta.objects.filter(id=cuenta.id).update(
                                        bloqueado=bool(bloqueado_dd),
                                        riesgo_motivo=("DRAWDOWN" if bloqueado_dd else ("CICLO_ACTIVO" if ciclo_habil else "OK")),
                                        ciclo_pausa_hasta_epoch=None,
                                        ciclo_balance_inicio=nuevo_ciclo_balance_inicio,
                                        ciclo_inicio_epoch=nuevo_ciclo_inicio_epoch,
                                        ciclo_ultimo_evento=("PAUSA_EXPIRADA_REINICIAR_CICLO" if ciclo_habil else "PAUSA_EXPIRADA_AUTO_CLEAR"),
                                        # Mantener updated_at consistente (para depuración/ordenamiento)
                                        updated_at=django_timezone.now(),
                                    ),
                                    thread_sensitive=True,
                                )()

                        # ===== EVALUACIÓN DE SEÑAL =====
                        if estrategia_tipo == "momentum" and estado_momentum is not None and MOMENTUM_AVAILABLE:
                            # Log de debug cada 100 ticks
                            if len(estado_momentum.precios) % 100 == 0:
                                _append_runtime_log(f"[{symbol}] [DEBUG] Usando estrategia momentum, precios={len(estado_momentum.precios)}")
                            # Usar estrategia Momentum Breakout
                            resultado_momentum = evaluar_momentum_breakout(
                                precio=float(tick_deriv.precio),
                                estado=estado_momentum,
                                **MOMENTUM_PARAMS
                            )
                            
                            # Convertir resultado a formato compatible
                            class ResultadoMomento:
                                def __init__(self, decision, razon, duracion_ticks=None, duracion_unit="t"):
                                    self.decision = decision
                                    self.razon = razon
                                    self.duracion_ticks = duracion_ticks
                                    self.duracion_unit = duracion_unit
                            
                            if resultado_momentum['decision'] == 'COMPRA':
                                resultado_spp = ResultadoMomento('COMPRA', resultado_momentum['razon'], 5, 't')
                            elif resultado_momentum['decision'] == 'VENTA':
                                resultado_spp = ResultadoMomento('VENTA', resultado_momentum['razon'], 5, 't')
                            else:
                                resultado_spp = ResultadoMomento('NO_OPERAR', resultado_momentum['razon'], None, 't')
                            
                            # Actualizar telemetría
                            ema_fast = estado_momentum.ema_rapida
                            ema_slow = estado_momentum.ema_lenta
                            gap = abs(ema_fast - ema_slow) if (ema_fast and ema_slow) else 0.0
                            volatilidad_100 = estado_momentum.volatilidad
                            
                            # Top contribuciones para el dashboard
                            momentum_val = estado_momentum.momentum
                            rsi_val = estado_momentum.rsi
                            vol_val = estado_momentum.volatilidad
                            
                            top_contrib = [
                                {"variable": "momentum", "contribucion": float(momentum_val), "x": float(momentum_val), "w": 1.0},
                                {"variable": "volatilidad", "contribucion": float(vol_val), "x": float(vol_val), "w": 1.0},
                                {"variable": "rsi", "contribucion": float(rsi_val), "x": float(rsi_val), "w": 1.0},
                                {"variable": "ema_9", "contribucion": float(ema_fast or 0.0), "x": float(ema_fast or 0.0), "w": 1.0},
                                {"variable": "ema_21", "contribucion": float(ema_slow or 0.0), "x": float(ema_slow or 0.0), "w": 1.0},
                            ]
                            
                        else:
                            # Usar estrategia SPP (por defecto)
                            resultado_spp: ResultadoSenalSPP = evaluar_senal_spp(
                                symbol=symbol,
                                precio=float(tick_deriv.precio),
                                estado=estado_spp,
                                ema_fast_period=int(getattr(settings, "SPP_EMA_FAST", 9)),
                                ema_slow_period=int(getattr(settings, "SPP_EMA_SLOW", 21)),
                            )
                            
                            # Telemetría para dashboard (sin máximos/mínimos)
                            ema_fast = float(estado_spp.ema_fast) if estado_spp.ema_fast is not None else None
                            ema_slow = float(estado_spp.ema_slow) if estado_spp.ema_slow is not None else None
                            gap = (abs(ema_fast - ema_slow) if (ema_fast is not None and ema_slow is not None) else None)
                            volatilidad_100 = 0.0
                            try:
                                ps = list(estado_spp.precios)
                                if len(ps) >= 3:
                                    # std de deltas de precio (últimos 100)
                                    deltas = [ps[i] - ps[i - 1] for i in range(max(1, len(ps) - 100), len(ps))]
                                    if len(deltas) >= 2:
                                        m = sum(deltas) / float(len(deltas))
                                        var = sum((d - m) ** 2 for d in deltas) / float(len(deltas))
                                        volatilidad_100 = float(var ** 0.5)
                            except Exception:
                                volatilidad_100 = 0.0

                            top_contrib = [
                                {"variable": "ema_50", "contribucion": float(ema_fast or 0.0), "x": float(ema_fast or 0.0), "w": 1.0},
                                {"variable": "ema_100", "contribucion": float(ema_slow or 0.0), "x": float(ema_slow or 0.0), "w": 1.0},
                                {"variable": "ema_gap", "contribucion": float(gap or 0.0), "x": float(gap or 0.0), "w": 1.0},
                            ]

                        # Telemetría para dashboard (sin máximos/mínimos)
                        ema_fast = float(estado_spp.ema_fast) if estado_spp.ema_fast is not None else None
                        ema_slow = float(estado_spp.ema_slow) if estado_spp.ema_slow is not None else None
                        gap = (abs(ema_fast - ema_slow) if (ema_fast is not None and ema_slow is not None) else None)
                        volatilidad_100 = 0.0
                        try:
                            ps = list(estado_spp.precios)
                            if len(ps) >= 3:
                                # std de deltas de precio (últimos 100)
                                deltas = [ps[i] - ps[i - 1] for i in range(max(1, len(ps) - 100), len(ps))]
                                if len(deltas) >= 2:
                                    m = sum(deltas) / float(len(deltas))
                                    var = sum((d - m) ** 2 for d in deltas) / float(len(deltas))
                                    volatilidad_100 = float(var ** 0.5)
                        except Exception:
                            volatilidad_100 = 0.0

                        top_contrib = [
                            {"variable": "ema_50", "contribucion": float(ema_fast or 0.0), "x": float(ema_fast or 0.0), "w": 1.0},
                            {"variable": "ema_100", "contribucion": float(ema_slow or 0.0), "x": float(ema_slow or 0.0), "w": 1.0},
                            {"variable": "ema_gap", "contribucion": float(gap or 0.0), "x": float(gap or 0.0), "w": 1.0},
                            {"variable": "volatilidad_100", "contribucion": float(volatilidad_100), "x": float(volatilidad_100), "w": 1.0},
                            {"variable": "pullback_len", "contribucion": float(estado_spp.pb_len), "x": float(estado_spp.pb_len), "w": 1.0},
                        ]

                        # Resultado compatible con el resto del flujo
                        from vector_pesos.senal import ResultadoSenal
                        resultado = ResultadoSenal(
                            valor=0.0,
                            decision=str(resultado_spp.decision),
                            contribuciones=None,
                        )

                        # ACTUALIZACIÓN "SUAVE" PARA DASHBOARD (NO ESCRIBIR EN CADA TICK).
                        # INCLUYE: ÚLTIMO TICK + TELEMETRÍA DE SEÑAL.
                        ahora = time.monotonic()
                        tiempo_desde_ultimo_persist = ahora - ultimo_persist
                        
                        # Preparar valores para dashboard
                        precio_actual_dash = tick_deriv.precio
                        epoch_actual_dash = tick_deriv.epoch
                        senal_valor_dash = resultado.valor if hasattr(resultado, 'valor') else 0.0
                        senal_decision_dash = resultado.decision
                        
                        # Extraer volatilidad y EMAs de top_contrib (ya calculados arriba)
                        volatilidad_100 = 0.0
                        ema_50 = None
                        ema_100 = None
                        if top_contrib:
                            for item in top_contrib:
                                if item.get("variable") == "volatilidad_100":
                                    volatilidad_100 = float(item.get("x", 0.0))
                                elif item.get("variable") == "ema_50":
                                    ema_50_val = item.get("x", 0.0)
                                    ema_50 = float(ema_50_val) if ema_50_val else None
                                elif item.get("variable") == "ema_100":
                                    ema_100_val = item.get("x", 0.0)
                                    ema_100 = float(ema_100_val) if ema_100_val else None
                        
                        # Log de diagnóstico cada 50 ticks
                        if ticks_procesados % 50 == 0:
                            _diag = (
                                f"[{symbol}] [DIAG] Tick #{ticks_procesados} estrategia=spp precio={precio_actual_dash:.5f} "
                                f"dec={senal_decision_dash} razon={getattr(resultado_spp,'razon', '-')}"
                            )
                            self.stdout.write(_diag)
                            _append_runtime_log(_diag)
                        
                        if tiempo_desde_ultimo_persist >= 1.0:
                            ultimo_persist = ahora
                            try:
                                # Actualizar cuenta en BD
                                # Nota: updated_at con auto_now=True no se actualiza con update(), 
                                # así que lo actualizamos manualmente
                                from django.utils import timezone as django_timezone
                                resultado_update = await sync_to_async(
                                    lambda: Cuenta.objects.filter(id=cuenta.id).update(
                                        ultimo_tick_epoch=int(epoch_actual_dash),
                                        ultimo_precio=float(precio_actual_dash),
                                        senal_valor=float(senal_valor_dash),
                                        senal_decision=str(senal_decision_dash),
                                        senal_top_contribuciones=top_contrib,
                                        updated_at=django_timezone.now(),
                                    ),
                                    thread_sensitive=True,
                                )()
                                # Verificar que se actualizó (resultado_update es el número de filas afectadas)
                                if resultado_update == 0:
                                    self.stderr.write(f"[UPDATE] ADVERTENCIA: update() afectó 0 filas (cuenta.id={cuenta.id} puede no existir)")
                                # Log cada 10 actualizaciones para verificar que funciona (sin saturar logs)
                                if ticks_procesados % 10 == 0:
                                    self.stdout.write(
                                        f"[UPDATE] BD actualizada: tick={epoch_actual_dash} precio={precio_actual_dash:.5f} "
                                        f"dec={senal_decision_dash} cuenta_id={cuenta.id} filas_afectadas={resultado_update}"
                                    )
                            except Exception as e:
                                # Log del error pero no romper el bot
                                import traceback
                                error_msg = f"[UPDATE] Error actualizando cuenta: {e}\n{traceback.format_exc()}"
                                self.stderr.write(error_msg)
                                self.stdout.write(self.style.ERROR(error_msg))

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
                        solo_monitoreo = bool(getattr(settings, "DERIV_SOLO_MONITOREO", False))
                        if modo_real and esperando is None and contrato_abierto_id is None:
                            if solo_monitoreo or gestor_riesgo.bloqueado:
                                # No enviar órdenes en modo monitoreo o si riesgo bloquea.
                                pass
                            elif resultado.decision in {"COMPRA", "VENTA"}:
                                # ===== LIMITADOR DE SESIÓN (anti-overtrading) =====
                                try:
                                    max_h = int(getattr(settings, "RISK_MAX_TRADES_PER_HOUR", 0) or 0)
                                    max_d = int(getattr(settings, "RISK_MAX_TRADES_PER_DAY", 0) or 0)
                                    now_ep = int(getattr(tick_deriv, "epoch", 0) or 0)
                                    if now_ep > 0 and (max_h > 0 or max_d > 0):
                                        if max_h > 0:
                                            desde_h = now_ep - 3600
                                            cnt_h = (
                                                OperacionDeriv.objects.filter(
                                                    cuenta_id=int(cuenta.id),
                                                    creada_por_bot=True,
                                                    opened_epoch__gte=int(desde_h),
                                                ).count()
                                            )
                                            if cnt_h >= max_h:
                                                msg = f"[{symbol}] [RISK] RATE_LIMIT hora: {cnt_h}/{max_h} (no abrir más)"
                                                self.stderr.write(msg)
                                                _append_runtime_log(msg)
                                                continue
                                        if max_d > 0:
                                            desde_d = now_ep - 86400
                                            cnt_d = (
                                                OperacionDeriv.objects.filter(
                                                    cuenta_id=int(cuenta.id),
                                                    creada_por_bot=True,
                                                    opened_epoch__gte=int(desde_d),
                                                ).count()
                                            )
                                            if cnt_d >= max_d:
                                                msg = f"[{symbol}] [RISK] RATE_LIMIT día: {cnt_d}/{max_d} (no abrir más)"
                                                self.stderr.write(msg)
                                                _append_runtime_log(msg)
                                                continue
                                except Exception:
                                    # Nunca tumbar el bot por un limitador.
                                    pass

                                dur_ml = None
                                # ===== FILTRO ML (LightGBM) =====
                                if getattr(self, "ml", None):
                                    feats = _features_from_precios(
                                        list(getattr(estado_spp, "precios", []) or []),
                                        epoch_actual_dash,
                                    )
                                    pred = self.ml.predict(symbol, feats) if feats else None
                                    if pred:
                                        prob, thr_ml = pred
                                        if prob < thr_ml:
                                            msg = f"[{symbol}] [ML] prob={prob:.3f} < thr={thr_ml:.3f} => SKIP entrada"
                                            self.stderr.write(msg)
                                            _append_runtime_log(msg)
                                            continue
                                        else:
                                            _append_runtime_log(f"[{symbol}] [ML] prob={prob:.3f} OK (thr={thr_ml:.3f})")
                                        # Duración: usar horizonte del modelo si viene en meta
                                        try:
                                            meta = self.ml.models.get(symbol, {}).get("meta", {})
                                            hor = int(meta.get("horizon_ticks") or meta.get("horizon") or 10)
                                            dur = max(1, min(hor, int(getattr(settings, "DERIV_MAX_DURACION_TICKS", 10) or 10)))
                                        except Exception:
                                            dur = int(getattr(settings, "DERIV_DURACION_TICKS", 5) or 5)
                                        dur_ml = dur

                                # STAKE:
                                # - Calculado como 1% del balance actual (crece proporcionalmente con el capital)
                                # - Mínimo: 0.35 USD (si el 1% es menor, usar 0.35)
                                # - Opcional: DERIV_STAKE_FIJO para forzar un monto (p.ej. 0.5 USD)
                                stake_fijo = getattr(settings, "DERIV_STAKE_FIJO", None)
                                balance_actual = float(gestor_riesgo.capital_actual)
                                min_stake = float(getattr(settings, "DERIV_MIN_STAKE", 1.0))
                                min_stake_dinamico = float(getattr(settings, "DERIV_MIN_STAKE_DINAMICO", 0.35))

                                if balance_actual <= 0.0:
                                    continue

                                # Base stake: fijo (si existe) o 1% del balance actual.
                                if stake_fijo is not None:
                                    try:
                                        stake = float(stake_fijo)
                                    except Exception:
                                        # Si stake_fijo es inválido, calcular como 1% del balance
                                        stake = balance_actual * 0.01
                                else:
                                    # Calcular como 1% del balance actual
                                    stake = balance_actual * 0.01

                                # Aplicar mínimo dinámico (0.35) si el stake calculado es menor
                                stake = max(float(stake), float(min_stake_dinamico))
                                
                                stake = max(min_stake, min(round(stake, 2), balance_actual))
                                if stake > 0:
                                    contract_type = "CALL" if resultado.decision == "COMPRA" else "PUT"

                                    # ===== GATING POR HORARIO (LOCAL) =====
                                    # Evita operar en ventanas malas pero permite que el proceso corra continuo 24/7.
                                    hora_local = None
                                    try:
                                        epoch_para_hora = tick.epoch if tick else epoch_actual_dash
                                        if epoch_para_hora:
                                            hora_local = self._hora_local(int(epoch_para_hora))
                                            # Log de diagnóstico (solo si está en horas bloqueadas o si hay problema)
                                            if hora_local is not None:
                                                if hora_local in horas_bloqueadas:
                                                    self.stderr.write(
                                                        f"[TRADING] SKIP horario_bloqueado hora={int(hora_local):02d} decision={resultado.decision} contract_type={contract_type}"
                                                    )
                                                    continue
                                    except Exception as e:
                                        # Si hay error calculando hora, loguear y bloquear por seguridad
                                        self.stderr.write(
                                            f"[TRADING] WARN error calculando hora_local: {e} epoch={epoch_para_hora if 'epoch_para_hora' in locals() else 'N/A'}. Bloqueando operación por seguridad."
                                        )
                                        continue
                                    
                                    # Si no se pudo calcular la hora, bloquear por seguridad
                                    if hora_local is None:
                                        self.stderr.write(
                                            f"[TRADING] WARN hora_local=None, bloqueando por seguridad. epoch={epoch_para_hora if 'epoch_para_hora' in locals() else 'N/A'}"
                                        )
                                        continue

                                    # ===== GATING POR CONTRACT TYPE =====
                                    # Permite apagar CALL o restringir tipos desde .env sin cambiar lógica.
                                    if contract_type not in contract_types_permitidos:
                                        self.stderr.write(
                                            f"[TRADING] SKIP contract_type_no_permitido decision={resultado.decision} contract_type={contract_type}"
                                        )
                                        continue

                                    # Duración: usar ML si está disponible, si no la estrategia base (7-15 ticks)
                                    if dur_ml is not None:
                                        dur = int(dur_ml)
                                    else:
                                        dur = int(getattr(resultado_spp, "duracion_ticks", 0) or 0)
                                        if dur <= 0:
                                            dur = 11 if symbol == "R_10" else 14

                                    # === AJUSTAR DURACIÓN A UNA VÁLIDA ===
                                    # Si tenemos duraciones disponibles del API, ajustar la duración solicitada
                                    # a la más cercana que sea válida.
                                    dur_deseada = int(dur)
                                    if duraciones_disponibles:
                                        # Encontrar la duración válida más cercana
                                        diff = min(abs(d - dur_deseada) for d in duraciones_disponibles)
                                        dur = next(d for d in duraciones_disponibles if abs(d - dur_deseada) == diff)
                                        if dur != dur_deseada:
                                            self.stderr.write(
                                                f"[TRADING] Duration adjusted {dur_deseada} -> {dur} (available: {duraciones_disponibles})"
                                            )
                                    else:
                                        # Detectar símbolos forex (frx*) que pueden tener límites diferentes
                                        is_forex = symbol.startswith("frx")
                                        # Para forex, usar límite más conservador por defecto (5 ticks)
                                        # ya que 10 ticks puede no estar disponible para forex
                                        default_abs_max = 5 if is_forex else 10

                                        dur_abs_max_cfg = int(getattr(settings, "DERIV_DUR_ABS_MAX", default_abs_max) or default_abs_max)

                                        dur_max_cfg = int(getattr(settings, "DERIV_MAX_DURACION_TICKS", default_abs_max) or default_abs_max)
                                        # max efectivo: respeta config pero nunca excede el límite absoluto conocido
                                        dur_max_eff = dur_abs_max_cfg if dur_max_cfg <= 0 else min(int(dur_max_cfg), dur_abs_max_cfg)

                                        dur = max(1, min(int(dur), int(dur_max_eff)))
                                        if dur != dur_deseada:
                                            ahora_w = time.monotonic()
                                            if (ahora_w - ultimo_warn_duracion) >= 5.0:
                                                ultimo_warn_duracion = ahora_w
                                                msg = (
                                                    f"[{symbol}] [TRADING] WARN duration_clamped desired={dur_deseada} "
                                                    f"-> using={dur} (max_cfg={dur_max_cfg}, max_deriv={dur_abs_max_cfg})"
                                                )
                                                self.stderr.write(msg)
                                                _append_runtime_log(msg)

                                    # Determinar unidad de duración basada en el resultado de la estrategia
                                    duration_unit = getattr(resultado_spp, "duracion_unit", "t")
                                    
                                    self.stderr.write(
                                        f"[TRADING] estrategia=spp decision={resultado.decision} stake={float(stake):.2f} "
                                        f"dur={dur}{duration_unit} contract_type={contract_type} razon={getattr(resultado_spp,'razon','-')}"
                                    )
                                    _append_runtime_log(
                                        f"[{symbol}] [TRADING] estrategia=spp decision={resultado.decision} stake={float(stake):.2f} "
                                        f"dur={dur}{duration_unit} contract_type={contract_type} razon={getattr(resultado_spp,'razon','-')}"
                                    )
                                    
                                    # Para forex, ajustar duración a minutos
                                    if symbol.startswith("frx") and duration_unit == "t":
                                        # Convertir ticks a minutos (5 minutos por defecto)
                                        dur = 5
                                        duration_unit = "m"
                                    
                                    await cliente.enviar(
                                        {
                                            "proposal": 1,
                                            "amount": float(stake),
                                            "basis": "stake",
                                            "contract_type": contract_type,
                                            "currency": (balance_moneda or "USD"),
                                            "duration": dur,
                                            "duration_unit": duration_unit,
                                            "symbol": symbol,
                                        }
                                    )
                                    
                                    # Determinar unidad de duración basada en el resultado de la estrategia
                                    duration_unit = getattr(resultado_spp, "duracion_unit", "t")
                                    if duration_unit == "m" and symbol.startswith("frx"):
                                        # Asegurar que para forex use minutos
                                        dur = getattr(resultado_spp, "duracion_ticks", 1) or 1
                                    
                                    await cliente.enviar(
                                        {
                                            "proposal": 1,
                                            "amount": float(stake),
                                            "basis": "stake",
                                            "contract_type": contract_type,
                                            "currency": (balance_moneda or "USD"),
                                            "duration": dur,
                                            "duration_unit": duration_unit,
                                            "symbol": symbol,
                                        }
                                    )
                                    
                                    # Guardar el umbral real usado para esta decisión (para auditoría en dashboard).
                                    umbral_guardar = None
                                    
                                    # Preparar datos para esperando
                                    senal_valor_guardar = 0.0
                                    pesos_usados_guardar = {}
                                    
                                    esperando = {
                                        "tipo": "proposal",
                                        "stake": float(stake),
                                        "senal_valor": senal_valor_guardar,
                                        "umbral_usado": umbral_guardar,
                                        "pesos_usados": pesos_usados_guardar,
                                        "senal_top_contribuciones": top_contrib,
                                        # Guardar spot de entrada (precio del índice) para persistirlo aunque Deriv no lo mande.
                                        "entry_spot": float(precio_actual_dash) if precio_actual_dash is not None else None,
                                        "duracion_ticks": int(dur) if duration_unit == "t" else None,
                                        "duracion_minutos": int(dur) if duration_unit == "m" else None,
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
                            epoch_log = tick.epoch if tick is not None else epoch_actual_dash
                            precio_log = tick.precio if tick is not None else precio_actual_dash
                            self.stdout.write(
                                f"t={epoch_log} p={precio_log:.5f} s={resultado.valor:.4f} dec={resultado.decision} "
                                f"cap={gestor_riesgo.capital_actual:.2f} bloqueado={gestor_riesgo.bloqueado} "
                                f"n={ticks_procesados}{top_txt}"
                            )
                            _append_runtime_log(
                                f"[{symbol}] t={epoch_log} p={precio_log:.5f} s={resultado.valor:.4f} dec={resultado.decision} "
                                f"cap={gestor_riesgo.capital_actual:.2f} bloqueado={gestor_riesgo.bloqueado} "
                                f"n={ticks_procesados}{top_txt}"
                            )

                        # ===== PAPER TRADING (DESACTIVADO EN MODO REAL) =====
                        if modo_real:
                            # EN MODO REAL NO SIMULAMOS POSICIONES INTERNAS (EVITA BLOQUEO POR "PAPER" Y CONFUSIÓN DE UI).
                            continue

                        # ===== PAPER TRADING + RIESGO (SÓLO PARA DEMOSTRAR GOBERNANZA) =====
                        # STOP DISTANCIA BASADA EN VOLATILIDAD LOCAL (PROPORCIONAL AL PRECIO).
                        # Nota: `x` no existe aquí. La volatilidad ya se calcula arriba como `volatilidad_100`
                        # (std de deltas de precio en ventana ~100). Usamos eso como proxy de vol local.
                        precio_mtm = float(getattr(tick, "precio", None) or precio_actual_dash or tick_deriv.precio)
                        vol = float(volatilidad_100 or 0.0)
                        stop_min = float(settings.STOP_MIN_PORCENTAJE) * float(precio_mtm)
                        stop_dist = max(stop_min, 2.0 * vol * precio_mtm)  # 2-sigma aproximado (simplificado)

                        # ACTUALIZAR EQUITY POR POSICIÓN ABIERTA (MARK-TO-MARKET SIMPLE CON STOP/TP).
                        if posicion is not None:
                            pnl = self._pnl_actual(posicion, precio_mtm)
                            capital_mtm = gestor_riesgo.capital_actual + pnl
                            gestor_riesgo.registrar_equity(capital_mtm)

                            # SALIDAS: STOP (1R) O TP (2R) SOBRE DISTANCIA STOP.
                            # Usar precio según estrategia activa
                            precio_cierre_paper = tick.precio if tick is not None else precio_actual_dash
                            if self._debe_cerrar(posicion, precio_cierre_paper):
                                gestor_riesgo.capital_actual = float(capital_mtm)

                                # CIERRE PERSISTENTE DE LA OPERACIÓN
                                if operacion_abierta is not None:
                                    # Usar precio y epoch según estrategia activa
                                    precio_cierre = tick.precio if tick is not None else precio_actual_dash
                                    epoch_cierre = tick.epoch if tick is not None else epoch_actual_dash
                                    motivo = self._motivo_cierre(operacion_abierta, float(precio_cierre))
                                    await sync_to_async(
                                        lambda: self._db_cerrar_operacion_y_actualizar_cuenta(
                                            operacion_id=int(operacion_abierta.id),
                                            cuenta_id=int(cuenta.id),
                                            precio_salida=float(precio_cierre),
                                            pnl=float(pnl),
                                            motivo=motivo,
                                            closed_epoch=int(epoch_cierre),
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
                                        precio_entrada=float(precio_actual_dash),
                                        tamanio=float(decision_riesgo.tamanio_posicion),
                                        stop_distancia=float(stop_dist),
                                        opened_epoch=int(epoch_actual_dash),
                                    ),
                                    thread_sensitive=True,
                                )()
                                # Usar precio según estrategia activa
                                precio_entrada_paper = tick.precio if tick is not None else precio_actual_dash
                                posicion = PosicionPaper(
                                    direccion=direccion,
                                    precio_entrada=float(precio_entrada_paper),
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
                                cap_vista = float(gestor_riesgo.capital_actual + self._pnl_actual(posicion, precio_mtm))
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
                _ws_to = f"[{symbol}] [WS] Timeout sin ticks (60s). Reintentando..."
                self.stderr.write(self.style.WARNING(_ws_to))
                _append_runtime_log(_ws_to)
                # IMPORTANTE: no conservar estados de órdenes a través de reconexión (evita quedar pegado).
                esperando = None
                esperando_desde = 0.0
                await dormir_segundos(3.0)
                continue
            except Exception as e:
                import traceback
                error_traceback = traceback.format_exc()
                _ws_err = f"[{symbol}] [WS] Error: {e}. Reintentando en 3s..."
                self.stderr.write(self.style.ERROR(_ws_err))
                self.stderr.write(f"[{symbol}] [WS] Traceback: {error_traceback}")
                _append_runtime_log(_ws_err)
                _append_runtime_log(f"[{symbol}] [WS] Traceback: {error_traceback}")
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
        qs = Cuenta.objects.filter(simbolo=simbolo).order_by("id")
        cuenta = qs.first()
        if cuenta is None:
            cuenta = Cuenta.objects.create(
                simbolo=simbolo,
                capital_inicial=float(settings.CAPITAL_INICIAL),
                capital_actual=float(settings.CAPITAL_INICIAL),
                max_capital_historico=float(settings.CAPITAL_INICIAL),
                bloqueado=False,
            )
        else:
            # Si hay duplicados por despliegues anteriores, usar siempre la más antigua (id más bajo)
            # para evitar “cambiar de cuenta” por timestamps/updated_at.
            try:
                if qs.count() > 1:
                    # No usamos logger para mantener el patrón de logs grepeables del comando.
                    # Nota: este warning no bloquea trading.
                    print(f"[CFG] WARN multiples Cuenta para simbolo={simbolo} usando cuenta_id={cuenta.id}")
            except Exception:
                pass

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
        entry_spot: float | None = None,
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
                "entry_spot": float(entry_spot) if entry_spot is not None else None,
            },
        )

    async def _procesar_profit_table(self, *, cuenta_id: int, raw: dict) -> None:
        """
        INGESTA HISTORIAL REAL DESDE `profit_table`.
        """
        tabla = raw.get("profit_table") or {}
        trans = tabla.get("transactions") or []

        def _actualizar_solo_existentes() -> None:
            from django.utils import timezone as django_timezone
            import time as time_module

            # REGLA: NO IMPORTAR HISTÓRICO COMPLETO DE DERIV.
            # SOLO ACTUALIZAR OPERACIONES YA CREADAS POR ESTE BOT (ENTRADAS REALES).
            # PERO: si encontramos una operación que no existe pero es reciente y del símbolo correcto,
            # la creamos (para recuperar operaciones perdidas tras reinicios).
            existentes = set(
                OperacionDeriv.objects.filter(cuenta_id=int(cuenta_id), creada_por_bot=True).values_list(
                    "contract_id", flat=True
                )
            )
            
            # Obtener el símbolo de la cuenta para validar
            cuenta_obj = Cuenta.objects.filter(id=int(cuenta_id)).first()
            simbolo_cuenta = cuenta_obj.simbolo if cuenta_obj else None
            
            # Timestamp actual para validar operaciones recientes (últimas 48 horas)
            ahora_epoch = int(time_module.time())
            max_edad_segundos = 48 * 3600  # 48 horas
            
            for t in trans:
                cid = t.get("contract_id")
                if cid is None:
                    continue
                cid_i = int(cid)
                simbolo_trans = str(t.get("symbol") or "")
                
                # Si no existe, intentar crearla si es reciente y del símbolo correcto
                if cid_i not in existentes:
                    purchase_time = t.get("purchase_time")
                    if purchase_time and simbolo_cuenta and simbolo_trans == simbolo_cuenta:
                        purchase_epoch = int(purchase_time)
                        edad_segundos = ahora_epoch - purchase_epoch
                        if 0 <= edad_segundos <= max_edad_segundos:
                            # Crear la operación que se perdió
                            buy_price = float(t.get("buy_price")) if t.get("buy_price") is not None else None
                            sell_price = float(t.get("sell_price")) if t.get("sell_price") is not None else None
                            entry_spot = float(t.get("entry_spot")) if t.get("entry_spot") is not None else None
                            exit_spot = float(t.get("exit_spot")) if t.get("exit_spot") is not None else None
                            if exit_spot is None and t.get("sell_spot") is not None:
                                try:
                                    exit_spot = float(t.get("sell_spot"))
                                except Exception:
                                    pass
                            profit = float(t.get("profit")) if t.get("profit") is not None else None
                            if profit is None and buy_price is not None and sell_price is not None:
                                profit = float(sell_price) - float(buy_price)
                            moneda = str(t.get("currency") or "")
                            if not moneda:
                                moneda = str(cuenta_obj.moneda_deriv if cuenta_obj else "")
                            
                            OperacionDeriv.objects.update_or_create(
                                contract_id=cid_i,
                                defaults={
                                    "cuenta_id": int(cuenta_id),
                                    "simbolo": simbolo_trans,
                                    "creada_por_bot": True,
                                    "transaction_id": int(t["transaction_id"]) if t.get("transaction_id") is not None else None,
                                    "contract_type": str(t.get("contract_type") or ""),
                                    "longcode": str(t.get("longcode") or ""),
                                    "shortcode": str(t.get("shortcode") or ""),
                                    "estado": OperacionDeriv.Estado.CERRADA if t.get("sell_time") else OperacionDeriv.Estado.ABIERTA,
                                    "moneda": moneda,
                                    "buy_price": buy_price,
                                    "sell_price": sell_price,
                                    "entry_spot": entry_spot,
                                    "exit_spot": exit_spot,
                                    "payout": float(t.get("payout")) if t.get("payout") is not None else None,
                                    "profit": profit,
                                    "opened_epoch": purchase_epoch,
                                    "closed_epoch": int(t.get("sell_time")) if t.get("sell_time") is not None else None,
                                    "updated_at": django_timezone.now(),
                                },
                            )
                            msg = f"[{simbolo_trans}] [PROFIT_TABLE] Operación {cid_i} RECUPERADA (no existía en BD): profit={profit}"
                            self.stdout.write(msg)
                            _append_runtime_log(msg)
                            # Agregar a existentes para que se actualice en el siguiente paso
                            existentes.add(cid_i)
                    else:
                        # No crear: es muy antigua o símbolo no coincide
                        continue
                buy_price = float(t.get("buy_price")) if t.get("buy_price") is not None else None
                sell_price = float(t.get("sell_price")) if t.get("sell_price") is not None else None
                # Spot (precio del índice) si Deriv lo entrega en profit_table (no siempre).
                entry_spot = float(t.get("entry_spot")) if t.get("entry_spot") is not None else None
                exit_spot = float(t.get("exit_spot")) if t.get("exit_spot") is not None else None
                if exit_spot is None and t.get("sell_spot") is not None:
                    try:
                        exit_spot = float(t.get("sell_spot"))
                    except Exception:
                        pass
                profit = float(t.get("profit")) if t.get("profit") is not None else None
                if profit is None and buy_price is not None and sell_price is not None:
                    # SI DERIV NO ENVÍA PROFIT EXPLÍCITO, SE DERIVA COMO SELL - BUY.
                    profit = float(sell_price) - float(buy_price)

                moneda = str(t.get("currency") or "")
                if not moneda:
                    moneda = str(Cuenta.objects.filter(id=int(cuenta_id)).values_list("moneda_deriv", flat=True).first() or "")

                # Deriv a veces NO envía `symbol` en profit_table. No debemos pisar el símbolo en BD con "".
                simbolo_payload = str(t.get("symbol") or "").strip()
                simbolo_existente = (
                    str(OperacionDeriv.objects.filter(contract_id=cid_i).values_list("simbolo", flat=True).first() or "").strip()
                )
                simbolo_final = simbolo_payload or simbolo_existente or (str(simbolo_cuenta or "").strip())

                # Importante: NO pisar entry_spot/exit_spot con NULL si Deriv no lo trae.
                update_kwargs = {
                    "simbolo": simbolo_final,
                    "transaction_id": int(t["transaction_id"]) if t.get("transaction_id") is not None else None,
                    "contract_type": str(t.get("contract_type") or ""),
                    "longcode": str(t.get("longcode") or ""),
                    "shortcode": str(t.get("shortcode") or ""),
                    "estado": OperacionDeriv.Estado.CERRADA if t.get("sell_time") else OperacionDeriv.Estado.ABIERTA,
                    "moneda": moneda,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "payout": float(t.get("payout")) if t.get("payout") is not None else None,
                    "profit": profit,
                    "opened_epoch": int(t.get("purchase_time")) if t.get("purchase_time") is not None else None,
                    "closed_epoch": int(t.get("sell_time")) if t.get("sell_time") is not None else None,
                }
                if entry_spot is not None:
                    update_kwargs["entry_spot"] = float(entry_spot)
                if exit_spot is not None:
                    update_kwargs["exit_spot"] = float(exit_spot)
                # CRÍTICO: Mantener creada_por_bot=True explícitamente para que no se pierda el flag
                # y la operación siga apareciendo en el dashboard después de cerrarse.
                update_kwargs["creada_por_bot"] = True

                estado_nuevo = update_kwargs.get("estado", "?")
                profit_val = update_kwargs.get("profit")
                simbolo_op = update_kwargs.get("simbolo") or simbolo_trans or "?"

                # Evitar “parpadeo” en dashboard:
                # No tocar updated_at si no cambió nada relevante (si no, el top-50 oscila entre días).
                existente_row = OperacionDeriv.objects.filter(contract_id=cid_i).values(
                    "simbolo",
                    "transaction_id",
                    "contract_type",
                    "longcode",
                    "shortcode",
                    "estado",
                    "moneda",
                    "buy_price",
                    "sell_price",
                    "payout",
                    "profit",
                    "opened_epoch",
                    "closed_epoch",
                    "entry_spot",
                    "exit_spot",
                    "creada_por_bot",
                ).first()
                if not existente_row:
                    # No debería pasar porque filtramos por existentes/recuperadas, pero por seguridad:
                    update_kwargs["updated_at"] = django_timezone.now()
                    OperacionDeriv.objects.filter(contract_id=cid_i).update(**update_kwargs)
                    continue

                # Comparar solo campos que realmente queremos mantener sincronizados.
                changed = False
                for k, v in update_kwargs.items():
                    # si Deriv no trae el campo (p. ej. entry_spot), no lo incluimos en update_kwargs
                    prev_v = existente_row.get(k)
                    if prev_v != v:
                        changed = True
                        break

                closed_prev = existente_row.get("closed_epoch")
                if changed:
                    update_kwargs["updated_at"] = django_timezone.now()
                    OperacionDeriv.objects.filter(contract_id=cid_i).update(**update_kwargs)
                
                # Log para debug: confirmar que se actualizó correctamente
                if (
                    changed
                    and estado_nuevo == OperacionDeriv.Estado.CERRADA
                    and closed_prev is None
                    and update_kwargs.get("closed_epoch") is not None
                ):
                    msg = f"[{simbolo_op}] [PROFIT_TABLE] Operación {cid_i} cerrada: profit={profit_val} updated_at={update_kwargs['updated_at']}"
                    self.stdout.write(msg)
                    _append_runtime_log(msg)

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
            entry_spot = float(contrato.get("entry_spot")) if contrato.get("entry_spot") is not None else None
            # Fallbacks típicos Deriv para spot de entrada/salida en contratos por ticks
            if entry_spot is None and contrato.get("entry_tick") is not None:
                try:
                    entry_spot = float(contrato.get("entry_tick"))
                except Exception:
                    pass
            # Deriv puede variar el nombre/available de spot de salida según estado.
            exit_spot = float(contrato.get("exit_spot")) if contrato.get("exit_spot") is not None else None
            if exit_spot is None and contrato.get("exit_tick") is not None:
                try:
                    exit_spot = float(contrato.get("exit_tick"))
                except Exception:
                    pass
            if exit_spot is None and contrato.get("sell_spot") is not None:
                try:
                    exit_spot = float(contrato.get("sell_spot"))
                except Exception:
                    pass
            # Fallback: si ya está sold, current_spot suele ser el spot final.
            if exit_spot is None and int(contrato.get("is_sold", 0)) == 1 and contrato.get("current_spot") is not None:
                try:
                    exit_spot = float(contrato.get("current_spot"))
                except Exception:
                    pass
            profit = float(contrato.get("profit")) if contrato.get("profit") is not None else None
            if profit is None and buy_price is not None and sell_price is not None:
                profit = float(sell_price) - float(buy_price)

            moneda = str(contrato.get("currency") or "")
            if not moneda:
                moneda = str(Cuenta.objects.filter(id=int(cuenta_id)).values_list("moneda_deriv", flat=True).first() or "")

            # Importante: no pisar spot existente con NULL si el payload no lo trae.
            existente = OperacionDeriv.objects.filter(contract_id=int(cid)).values("entry_spot", "exit_spot").first()
            if entry_spot is None and existente and existente.get("entry_spot") is not None:
                entry_spot = float(existente.get("entry_spot"))
            if exit_spot is None and existente and existente.get("exit_spot") is not None:
                exit_spot = float(existente.get("exit_spot"))

            # IMPORTANTE:
            # `proposal_open_contract` solo lo estamos consumiendo para contratos que este proceso abrió
            # (comprados por el bot o re-suscritos tras reconexión). Si no marcamos creada_por_bot=True,
            # el dashboard los oculta y parece que "no llegan" operaciones.
            from django.utils import timezone as django_timezone

            OperacionDeriv.objects.update_or_create(
                contract_id=int(cid),
                defaults={
                    "cuenta_id": int(cuenta_id),
                    "simbolo": str(simbolo),
                    "creada_por_bot": True,
                    "contract_type": str(contrato.get("contract_type") or ""),
                    "longcode": str(contrato.get("longcode") or ""),
                    "shortcode": str(contrato.get("shortcode") or ""),
                    "estado": OperacionDeriv.Estado.CERRADA if int(contrato.get("is_sold", 0)) == 1 else OperacionDeriv.Estado.ABIERTA,
                    "moneda": moneda,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "entry_spot": entry_spot,
                    "exit_spot": exit_spot,
                    "payout": float(contrato.get("payout")) if contrato.get("payout") is not None else None,
                    "profit": profit,
                    "opened_epoch": int(contrato.get("date_start")) if contrato.get("date_start") is not None else None,
                    "closed_epoch": int(contrato.get("sell_time")) if contrato.get("sell_time") is not None else None,
                    # Asegura orden correcto en "últimas 50"
                    "updated_at": django_timezone.now(),
                },
            )

        await sync_to_async(_upsert, thread_sensitive=True)()


