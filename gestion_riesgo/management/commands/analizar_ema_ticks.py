from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.core.management.base import BaseCommand


@dataclass(frozen=True)
class Tick:
    epoch: int
    price: float


@dataclass
class Perf:
    n: int = 0
    wins: int = 0
    losses: int = 0
    ev: float = 0.0  # expected value in "stake=1" units over all trades (sum outcome)

    def winrate(self) -> float:
        return (self.wins / self.n) if self.n else 0.0


def _read_ticks_csv(path: Path) -> tuple[str, list[Tick]]:
    ticks: list[Tick] = []
    symbol = "?"
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                epoch = int(float(row["epoch"]))
                price = float(row["price"])
                symbol = str(row.get("symbol") or symbol).strip() or symbol
                ticks.append(Tick(epoch=epoch, price=price))
            except Exception:
                continue
    ticks.sort(key=lambda t: t.epoch)
    return symbol, ticks


def _ema(series: list[float], period: int) -> list[float]:
    if period <= 1:
        return series[:]
    alpha = 2.0 / (period + 1.0)
    out: list[float] = []
    ema = series[0]
    out.append(ema)
    for x in series[1:]:
        ema = (alpha * x) + ((1.0 - alpha) * ema)
        out.append(ema)
    return out


def _rolling_flips(signs: list[int], window: int) -> list[int]:
    # flips = count of sign changes within window
    if window <= 1:
        return [0 for _ in signs]
    out = [0] * len(signs)
    flips = 0
    # track flips in a sliding window by storing boundaries of sign changes
    change_idx: list[int] = []
    for i in range(1, len(signs)):
        if signs[i] != signs[i - 1]:
            change_idx.append(i)
    # two-pointer count of changes in [i-window+1, i]
    j = 0
    for i in range(len(signs)):
        left = i - window + 1
        while j < len(change_idx) and change_idx[j] < left:
            j += 1
        k = j
        while k < len(change_idx) and change_idx[k] <= i:
            k += 1
        out[i] = max(0, k - j)
    return out


@dataclass(frozen=True)
class Config:
    ema_fast: int
    ema_slow: int
    slope_n: int
    min_gap: float
    pullback_max: int
    choppy_w: int
    choppy_max_flips: int
    dur_ticks: int


def _simulate_ema_pullback(
    *,
    prices: list[float],
    payout_win: float,
    cfg: Config,
) -> Perf:
    perf = Perf()
    if len(prices) < max(cfg.ema_fast, cfg.ema_slow, cfg.slope_n) + cfg.dur_ticks + 5:
        return perf

    ef = _ema(prices, cfg.ema_fast)
    es = _ema(prices, cfg.ema_slow)

    # slope of fast EMA over slope_n
    slope = [0.0] * len(prices)
    for i in range(cfg.slope_n, len(prices)):
        slope[i] = ef[i] - ef[i - cfg.slope_n]

    gap = [abs(ef[i] - es[i]) for i in range(len(prices))]
    sign_rel = [1 if prices[i] >= ef[i] else -1 for i in range(len(prices))]
    flips = _rolling_flips(sign_rel, cfg.choppy_w)

    # Pullback state
    pb_len = 0
    pb_dir = None  # "CALL" or "PUT"

    for i in range(1, len(prices) - cfg.dur_ticks - 1):
        # anti-chop
        if flips[i] > cfg.choppy_max_flips:
            pb_len = 0
            pb_dir = None
            continue

        # trend bias
        bias = None
        if ef[i] > es[i] and gap[i] >= cfg.min_gap and slope[i] > 0:
            bias = "CALL"
        elif ef[i] < es[i] and gap[i] >= cfg.min_gap and slope[i] < 0:
            bias = "PUT"
        else:
            pb_len = 0
            pb_dir = None
            continue

        # detect pullback: in CALL bias we want price below ef; in PUT bias price above ef
        if bias == "CALL":
            if prices[i] < ef[i]:
                pb_len += 1
                pb_dir = "CALL"
                if pb_len > cfg.pullback_max:
                    pb_len = 0
                    pb_dir = None
                continue
            # reclaim: price back above ef after pullback
            if pb_dir == "CALL" and pb_len > 0 and prices[i] >= ef[i]:
                entry = prices[i]
                exit_p = prices[i + cfg.dur_ticks]
                perf.n += 1
                if exit_p > entry:
                    perf.wins += 1
                    perf.ev += float(payout_win)
                else:
                    perf.losses += 1
                    perf.ev -= 1.0
                pb_len = 0
                pb_dir = None
        else:  # PUT bias
            if prices[i] > ef[i]:
                pb_len += 1
                pb_dir = "PUT"
                if pb_len > cfg.pullback_max:
                    pb_len = 0
                    pb_dir = None
                continue
            if pb_dir == "PUT" and pb_len > 0 and prices[i] <= ef[i]:
                entry = prices[i]
                exit_p = prices[i + cfg.dur_ticks]
                perf.n += 1
                if exit_p < entry:
                    perf.wins += 1
                    perf.ev += float(payout_win)
                else:
                    perf.losses += 1
                    perf.ev -= 1.0
                pb_len = 0
                pb_dir = None

    return perf


def _grid() -> Iterable[Config]:
    # grid conservador (rápido) pensado para ticks (no velas)
    ema_fast_vals = [20, 50]
    ema_slow_vals = [50, 100, 200]
    slope_n_vals = [5, 10]
    pullback_max_vals = [3, 5, 7]
    dur_vals = [5, 7, 10]
    # choppy: flips de precio vs EMAfast
    choppy_w_vals = [20, 40]
    choppy_max_flips_vals = [10, 14]
    # min_gap se ajusta por escala del activo => lo estimamos como percentil después
    for ef in ema_fast_vals:
        for es in ema_slow_vals:
            if ef >= es:
                continue
            for sn in slope_n_vals:
                for pb in pullback_max_vals:
                    for cw in choppy_w_vals:
                        for cmf in choppy_max_flips_vals:
                            for d in dur_vals:
                                yield Config(
                                    ema_fast=ef,
                                    ema_slow=es,
                                    slope_n=sn,
                                    min_gap=0.0,  # placeholder, se setea luego
                                    pullback_max=pb,
                                    choppy_w=cw,
                                    choppy_max_flips=cmf,
                                    dur_ticks=d,
                                )


class Command(BaseCommand):
    help = "Analiza CSVs de ticks con patrones EMA (trend+pullback+anti-chop) y reporta configs ganadoras."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument(
            "--files",
            type=str,
            default="",
            help="CSV(s) separados por coma. Si vacío, busca en data/ticks/*.csv",
        )
        parser.add_argument("--outdir", type=str, default="data/ticks", help="Directorio por defecto (data/ticks)")
        parser.add_argument(
            "--payout-win",
            type=float,
            default=0.8857,
            help="Payout ganador en unidades de stake=1 (default ≈ 0.31/0.35=0.8857)",
        )
        parser.add_argument("--min-trades", type=int, default=30, help="Mín trades para considerar config (default: 30)")
        parser.add_argument("--top", type=int, default=8, help="Top configs a mostrar por símbolo (default: 8)")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        files_raw = str(opts.get("files") or "").strip()
        outdir = Path(str(opts.get("outdir") or "data/ticks"))
        payout_win = float(opts.get("payout_win") or 0.8857)
        min_trades = int(opts.get("min_trades") or 30)
        top_n = int(opts.get("top") or 8)

        if files_raw:
            paths = [Path(p.strip()) for p in files_raw.split(",") if p.strip()]
        else:
            paths = sorted(outdir.glob("*.csv"))

        if not paths:
            self.stdout.write("No encontré CSVs. Primero ejecuta: python manage.py capturar_ticks --minutos 30")
            return

        self.stdout.write("=" * 100)
        self.stdout.write("ANÁLISIS EMA (trend+pullback+anti-chop) — resultados por símbolo")
        self.stdout.write("=" * 100)
        self.stdout.write(f"payout_win={payout_win:.4f}  breakeven_wr≈{(1.0/(1.0+payout_win))*100:.2f}%")
        self.stdout.write("")

        by_symbol: dict[str, list[list[Tick]]] = {}
        for p in paths:
            sym, ticks = _read_ticks_csv(p)
            if len(ticks) < 200:
                continue
            by_symbol.setdefault(sym, []).append(ticks)

        if not by_symbol:
            self.stdout.write("No hay datasets suficientes (archivos muy cortos o vacíos).")
            return

        for sym, datasets in sorted(by_symbol.items()):
            # unimos datasets por símbolo (por si capturaste varias veces)
            merged: list[Tick] = []
            for ds in datasets:
                merged.extend(ds)
            merged.sort(key=lambda t: t.epoch)
            # de-dup por epoch
            uniq: list[Tick] = []
            seen = set()
            for t in merged:
                if t.epoch in seen:
                    continue
                seen.add(t.epoch)
                uniq.append(t)

            prices = [t.price for t in uniq]

            # min_gap adaptativo por escala: percentiles del gap (EMA50-EMA100) como referencia
            # usamos un “proxy” rápido para definir gaps: std de retornos * factor
            rets = []
            for i in range(1, len(prices)):
                rets.append(prices[i] - prices[i - 1])
            std = math.sqrt(sum(r * r for r in rets) / max(1, len(rets)))
            # gap mínimo candidatos: 1x, 2x, 3x de std (en unidades de precio)
            gap_candidates = [max(0.0, std * f) for f in (1.0, 2.0, 3.0)]

            results: list[tuple[Perf, Config]] = []
            for base_cfg in _grid():
                for mg in gap_candidates:
                    cfg = Config(
                        ema_fast=base_cfg.ema_fast,
                        ema_slow=base_cfg.ema_slow,
                        slope_n=base_cfg.slope_n,
                        min_gap=float(mg),
                        pullback_max=base_cfg.pullback_max,
                        choppy_w=base_cfg.choppy_w,
                        choppy_max_flips=base_cfg.choppy_max_flips,
                        dur_ticks=base_cfg.dur_ticks,
                    )
                    perf = _simulate_ema_pullback(prices=prices, payout_win=payout_win, cfg=cfg)
                    if perf.n >= min_trades:
                        results.append((perf, cfg))

            if not results:
                self.stdout.write(f"## {sym}: no hay configs con >= {min_trades} trades en este dataset")
                self.stdout.write("")
                continue

            # Ordenar por EV total (sum) y luego por winrate
            results.sort(key=lambda x: (x[0].ev, x[0].winrate()), reverse=True)

            self.stdout.write(f"## {sym}")
            self.stdout.write(f"- ticks={len(prices)}  std_ret≈{std:.6f}  gap_candidates={', '.join(f'{g:.6f}' for g in gap_candidates)}")
            self.stdout.write(f"- top {top_n} configs (EV en stake=1; win=+{payout_win:.3f}, loss=-1.0)")
            for perf, cfg in results[:top_n]:
                wr = perf.winrate() * 100.0
                avg_ev = (perf.ev / perf.n) if perf.n else 0.0
                self.stdout.write(
                    f"  - n={perf.n} wr={wr:.1f}% ev_total={perf.ev:.2f} ev_avg={avg_ev:.4f} | "
                    f"ema={cfg.ema_fast}/{cfg.ema_slow} slope_n={cfg.slope_n} min_gap={cfg.min_gap:.6f} "
                    f"pb_max={cfg.pullback_max} chop_w={cfg.choppy_w} chop_flips<={cfg.choppy_max_flips} dur={cfg.dur_ticks}"
                )
            self.stdout.write("")

