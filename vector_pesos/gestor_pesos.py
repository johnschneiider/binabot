from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class GestorPesos:
    """
    ADMINISTRA EL VECTOR DE PESOS (w) QUE DEFINE LA ESTRATEGIA.

    PRINCIPIO INSTITUCIONAL:
    - PESOS = ESTRATEGIA. EL MERCADO NO SE MODIFICA AQUÍ.
    - ESTE MÓDULO ES UNA "INTERFAZ" LIMPIA PARA REEMPLAZAR PESOS FIJOS POR IA FUTURA.
    """

    _pesos: dict[str, float] = field(default_factory=dict)
    _ruta_archivo: str | None = None
    _cache_mtime: float | None = None
    _cache_archivo: dict[str, float] = field(default_factory=dict)

    @classmethod
    def con_pesos_fijos_por_defecto(cls, *, ruta_archivo: str | None = None) -> "GestorPesos":
        """
        CREA UNA CONFIGURACIÓN INICIAL DE PESOS FIJOS Y EDITABLES.

        NOTA:
        - ESTOS PESOS SON UN PUNTO DE PARTIDA. SE AJUSTAN EN PRODUCCIÓN CON BACKTEST/RESEARCH.
        """
        return cls(
            _pesos={
                # VARIABLES OBLIGATORIAS (MISMO NOMBRE QUE EL VECTOR x)
                "retorno_instantaneo": 0.10,
                "ema_rapida": 0.05,
                "ema_lenta": -0.05,
                "rsi_ticks": 0.02,
                "volatilidad_local": -0.20,
                "skewness": 0.05,
                "kurtosis": -0.10,
                "tasa_ticks": 0.05,
            },
            _ruta_archivo=str(ruta_archivo) if ruta_archivo else None,
        )

    def _leer_archivo_si_cambio(self) -> None:
        """
        RECARGA PESOS DESDE JSON SI EXISTE Y CAMBIÓ (MTIME).

        POR QUÉ:
        - PERMITE QUE UN CALIBRADOR ACTUALICE w SIN REINICIAR TODO EL SISTEMA.
        - MANTIENE ESTA CAPA COMO "ESTRATEGIA": FUENTE EXTERNA (ARCHIVO/IA) PUEDE INYECTAR PESOS.
        """
        ruta = self._ruta_archivo
        if not ruta:
            return
        try:
            st = os.stat(ruta)
        except FileNotFoundError:
            self._cache_mtime = None
            self._cache_archivo = {}
            return

        mtime = float(st.st_mtime)
        if self._cache_mtime is not None and mtime <= float(self._cache_mtime):
            return

        try:
            with open(ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            # SI EL ARCHIVO ESTÁ A MEDIO ESCRIBIR O CORRUPTO, NO ROMPER EL BOT.
            return

        pesos = data.get("pesos") if isinstance(data, dict) else None
        if not isinstance(pesos, dict):
            return

        nuevo: dict[str, float] = {}
        for k, v in pesos.items():
            try:
                nuevo[str(k)] = float(v)
            except Exception:
                continue

        self._cache_archivo = nuevo
        self._cache_mtime = mtime

    def obtener_pesos_actuales(self) -> dict[str, float]:
        """
        DEVUELVE UNA COPIA DEL VECTOR DE PESOS ACTUAL.

        POR QUÉ:
        - EVITA QUE OTROS MÓDULOS MUTEN EL ESTADO INTERNAMENTE.
        """
        self._leer_archivo_si_cambio()
        # REGLA: BASE (FIJOS) + OVERRIDE DESDE ARCHIVO (SI EXISTE).
        out = dict(self._pesos)
        out.update(dict(self._cache_archivo))
        return out

    def actualizar_pesos(self, nuevos_pesos: dict[str, float]) -> None:
        """
        ACTUALIZA PESOS DE FORMA CONTROLADA.

        REGLA:
        - SOLO ACTUALIZA CLAVES EXISTENTES O AGREGA NUEVAS SI SE HA AMPLIADO EL VECTOR.
        """
        for k, v in nuevos_pesos.items():
            self._pesos[str(k)] = float(v)

    # ===== PREPARACIÓN PARA IA FUTURA =====
    def obtener_pesos_desde_ia(self, vector_mercado: dict[str, float]) -> dict[str, float]:
        """
        INTERFAZ PARA IA EXTERNA (FUTURO).

        QUÉ HACE HOY:
        - DEVUELVE LOS PESOS ACTUALES (FIJOS).

        QUÉ HARÁ MAÑANA:
        - LLAMAR A UN SERVICIO/MODELO ENTRENADO QUE DEVUELVA PESOS CONDICIONADOS AL ESTADO x.
        """
        _ = vector_mercado
        return self.obtener_pesos_actuales()


