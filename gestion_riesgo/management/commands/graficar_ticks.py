from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, List, Tuple

import matplotlib

# Backend "Agg" permite renderizar sin display (servidores/headless).
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from django.core.management.base import BaseCommand

from gestion_riesgo.models import TickDerivHistorico


def _sample_ticks(
    symbol: str,
    max_points: int,
    chunk_size: int = 10_000,
) -> Tuple[List[int], List[float], int]:
    """
    Lee ticks de la BD para un símbolo, ordenados por epoch, y devuelve
    una muestra espaciada (stride) para no cargar en memoria millones de puntos.
    """
    qs = (
        TickDerivHistorico.objects.filter(cuenta__simbolo=symbol)
        .order_by("epoch")
        .values_list("epoch", "precio")
    )
    total = qs.count()
    if total == 0:
        return [], [], 0

    step = max(1, math.ceil(total / max_points))  # stride dinámico
    xs: List[int] = []
    ys: List[float] = []

    idx = 0
    for epoch, precio in qs.iterator(chunk_size=chunk_size):
        if idx % step == 0:
            xs.append(int(epoch))
            ys.append(float(precio))
        idx += 1

    return xs, ys, total


class Command(BaseCommand):
    help = "Genera un gráfico de dispersión (scatter) de los ticks históricos almacenados en BD."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument(
            "--simbolos",
            type=str,
            default="R_10,R_100",
            help='Lista separada por coma (default: "R_10,R_100")',
        )
        parser.add_argument(
            "--max-points",
            type=int,
            default=20_000,
            help="Máximo de puntos por símbolo para graficar (muestra espaciada).",
        )
        parser.add_argument(
            "--outdir",
            type=str,
            default="plots",
            help='Directorio de salida (default: "plots").',
        )
        parser.add_argument(
            "--outfile",
            type=str,
            default="scatter_ticks.png",
            help='Nombre del archivo PNG (default: "scatter_ticks.png").',
        )

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        symbols_raw = str(opts.get("simbolos") or "").strip()
        symbols: Iterable[str] = [s.strip() for s in symbols_raw.split(",") if s.strip()]
        max_points = max(1, int(opts.get("max_points") or 20_000))

        outdir = Path(str(opts.get("outdir") or "plots")).resolve()
        outdir.mkdir(parents=True, exist_ok=True)
        outfile = outdir / str(opts.get("outfile") or "scatter_ticks.png")

        plt.figure(figsize=(12, 6))
        plotted = 0

        for sym in symbols:
            xs_epoch, ys_price, total = _sample_ticks(sym, max_points)
            if not xs_epoch:
                self.stdout.write(f"[{sym}] Sin datos en TickDerivHistorico.")
                continue
            # Convertir epoch a datetime para eje X legible
            xs_dt = [matplotlib.dates.epoch2num(x) for x in xs_epoch]
            plt.scatter(xs_dt, ys_price, s=2, alpha=0.5, label=f"{sym} (n={len(xs_epoch)}/{total})")
            self.stdout.write(f"[{sym}] total={total} graficados={len(xs_epoch)} step≈{max(1, math.ceil(total/max_points))}")
            plotted += len(xs_epoch)

        if plotted == 0:
            self.stdout.write("No hay datos para graficar.")
            return

        plt.title("Scatter ticks históricos (muestra)")
        plt.xlabel("Tiempo (UTC)")
        plt.ylabel("Precio")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.gcf().autofmt_xdate()

        plt.savefig(outfile, dpi=150)
        self.stdout.write(f"Guardado: {outfile}")

