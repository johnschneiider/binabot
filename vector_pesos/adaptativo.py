from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field


def _wilson_lower_bound(*, wins: int, n: int, z: float = 1.645) -> float:
    """
    Wilson score interval (lower bound) for a binomial proportion.

    - wins: number of successes
    - n: total trials
    - z: z-score (1.645 ~ 90% one-sided; conservative but not too strict)
    """
    if n <= 0:
        return 0.0
    k = max(0, min(int(wins), int(n)))
    n = int(n)
    phat = k / n
    z2 = float(z) ** 2
    denom = 1.0 + z2 / n
    center = phat + z2 / (2.0 * n)
    margin = float(z) * ((phat * (1.0 - phat) + z2 / (4.0 * n)) / n) ** 0.5
    low = (center - margin) / denom
    return float(max(0.0, min(1.0, low)))


@dataclass
class EstadoUmbral:
    """
    Estadística acumulada por umbral candidato.
    """

    wins: int = 0
    losses: int = 0

    @property
    def n(self) -> int:
        return int(self.wins + self.losses)

    @property
    def winrate(self) -> float:
        if self.n <= 0:
            return 0.0
        return float(self.wins / self.n)


@dataclass
class AdaptadorUmbralOnline:
    """
    Ajusta el umbral de operación en vivo basándose en resultados reales.

    Idea:
    - Mantener un conjunto discreto de umbrales candidatos |s|>=t.
    - Cada trade cerrado actualiza (off-policy) todos los umbrales t <= |score_entrada|.
    - Elegir el umbral MÁS BAJO que cumpla una condición conservadora de edge:
        WilsonLowerBound(winrate) >= breakeven_winrate + margen
      con un mínimo de trades.

    Seguridad:
    - Si ningún umbral cumple, se devuelve un umbral "infinito" => NO operar.
    - No toca pesos w; solo gobierna cuándo entrar.
    """

    thresholds: list[float]
    payout_win: float
    costo_por_trade: float
    min_trades: int
    edge_margin: float
    archivo_estado: str
    z_wilson: float = 1.645

    _estado: dict[str, EstadoUmbral] = field(default_factory=dict)
    _cache_mtime: float | None = None
    _ultimo_guardado: float = 0.0

    def __post_init__(self) -> None:
        self.thresholds = sorted({float(abs(t)) for t in self.thresholds if float(abs(t)) > 0.0})
        if not self.thresholds:
            # fallback ultra conservador
            self.thresholds = [0.10, 0.13, 0.17]
        for t in self.thresholds:
            self._estado.setdefault(str(t), EstadoUmbral())

    def breakeven_winrate(self) -> float:
        # stake=1: EV = p*payout - (1-p)*1 - cost  => EV>0 => p > (1+cost)/(1+payout)
        payout = float(self.payout_win)
        cost = float(self.costo_por_trade)
        denom = 1.0 + payout
        if denom <= 0:
            return 1.0
        return float((1.0 + cost) / denom)

    def _leer_archivo_si_cambio(self) -> None:
        ruta = str(self.archivo_estado or "").strip()
        if not ruta:
            return
        try:
            st = os.stat(ruta)
        except FileNotFoundError:
            self._cache_mtime = None
            return
        mtime = float(st.st_mtime)
        if self._cache_mtime is not None and mtime <= float(self._cache_mtime):
            return
        try:
            data = json.load(open(ruta, "r", encoding="utf-8"))
        except Exception:
            return
        est = data.get("estado") if isinstance(data, dict) else None
        if not isinstance(est, dict):
            return
        for k, v in est.items():
            if not isinstance(v, dict):
                continue
            wins = v.get("wins")
            losses = v.get("losses")
            try:
                kk = str(float(k))
                self._estado[kk] = EstadoUmbral(wins=int(wins or 0), losses=int(losses or 0))
            except Exception:
                continue
        self._cache_mtime = mtime

    def _guardar(self, force: bool = False) -> None:
        ruta = str(self.archivo_estado or "").strip()
        if not ruta:
            return
        ahora = time.monotonic()
        if not force and (ahora - float(self._ultimo_guardado)) < 2.0:
            return
        payload = {
            "updated_at_epoch": int(time.time()),
            "breakeven_winrate": self.breakeven_winrate(),
            "edge_margin": float(self.edge_margin),
            "min_trades": int(self.min_trades),
            "thresholds": list(self.thresholds),
            "estado": {k: {"wins": v.wins, "losses": v.losses} for k, v in self._estado.items()},
        }
        try:
            os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self._ultimo_guardado = ahora
            try:
                self._cache_mtime = float(os.stat(ruta).st_mtime)
            except Exception:
                pass
        except Exception:
            return

    def registrar_trade_cerrado(self, *, score_entrada: float, gano: bool) -> None:
        """
        Actualiza contadores para todos los umbrales que habrían tomado el trade.
        """
        self._leer_archivo_si_cambio()
        s_abs = float(abs(score_entrada))
        for t in self.thresholds:
            if s_abs + 1e-12 < float(t):
                continue
            st = self._estado.setdefault(str(t), EstadoUmbral())
            if bool(gano):
                st.wins += 1
            else:
                st.losses += 1
        self._guardar(force=False)

    def umbral_actual(self) -> float:
        """
        Retorna el umbral recomendado (positivo). La venta debe usar el negativo.
        Si no hay edge suficiente, devuelve +inf (=> no operar).
        """
        self._leer_archivo_si_cambio()
        be = self.breakeven_winrate()
        target = float(be + float(self.edge_margin))

        mejor: float | None = None
        for t in self.thresholds:
            st = self._estado.get(str(t)) or EstadoUmbral()
            if st.n < int(self.min_trades):
                continue
            lb = _wilson_lower_bound(wins=st.wins, n=st.n, z=float(self.z_wilson))
            if lb >= target:
                mejor = float(t) if mejor is None else min(float(mejor), float(t))

        return float(mejor) if mejor is not None else float("inf")


