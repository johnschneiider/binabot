from __future__ import annotations

import asyncio
import csv
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS


@dataclass(frozen=True)
class CapturaCfg:
    symbol: str
    segundos: int
    out_csv: Path


async def _capturar_un_symbol(cfg: CapturaCfg) -> dict:
    inicio = time.time()
    fin = inicio + float(cfg.segundos)
    n = 0
    first_epoch = None
    last_epoch = None
    last_price = None

    cfg.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with cfg.out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "price", "symbol"])

        async with ClienteDerivWS(token=None) as c:
            async for t in c.stream_ticks(cfg.symbol):
                now = time.time()
                if now > fin:
                    break
                n += 1
                if first_epoch is None:
                    first_epoch = int(t.epoch)
                last_epoch = int(t.epoch)
                last_price = float(t.precio)
                w.writerow([int(t.epoch), float(t.precio), str(t.symbol)])

    dur = time.time() - inicio
    return {
        "symbol": cfg.symbol,
        "ticks": n,
        "seconds": dur,
        "first_epoch": first_epoch,
        "last_epoch": last_epoch,
        "last_price": last_price,
        "file": str(cfg.out_csv),
    }


class Command(BaseCommand):
    help = "Captura ticks en vivo de R_10/R_100 a CSV para análisis (EMA/patrones)."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument(
            "--simbolos",
            type=str,
            default="R_10,R_100",
            help='Lista separada por coma (default: "R_10,R_100")',
        )
        parser.add_argument("--minutos", type=int, default=30, help="Minutos de captura (default: 30)")
        parser.add_argument(
            "--outdir",
            type=str,
            default="data/ticks",
            help="Directorio de salida relativo al proyecto (default: data/ticks)",
        )

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        simbolos = [s.strip() for s in str(opts.get("simbolos") or "").split(",") if s.strip()]
        minutos = int(opts.get("minutos") or 30)
        segundos = max(1, int(minutos * 60))
        outdir = Path(str(opts.get("outdir") or "data/ticks"))
        # Si lo ejecutas desde manage.py, cwd suele ser BASE_DIR. Igual lo normalizamos:
        try:
            base = Path(getattr(settings, "BASE_DIR", Path(".")))
        except Exception:
            base = Path(".")
        outdir_abs = (base / outdir).resolve()

        ts = int(time.time())
        cfgs: list[CapturaCfg] = []
        for sym in simbolos:
            out_csv = outdir_abs / f"ticks_{sym}_{ts}.csv"
            cfgs.append(CapturaCfg(symbol=sym, segundos=segundos, out_csv=out_csv))

        self.stdout.write(f"Capturando ticks {minutos} min para: {simbolos}")
        self.stdout.write(f"Salida: {str(outdir_abs)}")
        self.stdout.write("Esto tarda en tiempo real (captura en vivo).")

        async def runner() -> list[dict]:
            tasks = [asyncio.create_task(_capturar_un_symbol(c)) for c in cfgs]
            return await asyncio.gather(*tasks)

        resultados = asyncio.run(runner())

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("RESUMEN CAPTURA")
        self.stdout.write("=" * 80)
        for r in resultados:
            self.stdout.write(
                f"- {r['symbol']}: ticks={r['ticks']} secs≈{r['seconds']:.1f} "
                f"first_epoch={r['first_epoch']} last_epoch={r['last_epoch']} last_price={r['last_price']} "
                f"file={r['file']}"
            )

