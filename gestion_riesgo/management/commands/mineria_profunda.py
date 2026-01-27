from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion_riesgo.models import OperacionDeriv


@dataclass
class Stats:
    n: int = 0
    wins: int = 0
    losses: int = 0
    profit_total: float = 0.0
    sum_win: float = 0.0
    sum_loss_abs: float = 0.0

    def add(self, p: float) -> None:
        self.n += 1
        self.profit_total += float(p)
        if p > 0:
            self.wins += 1
            self.sum_win += float(p)
        else:
            self.losses += 1
            self.sum_loss_abs += abs(float(p))

    def winrate(self) -> float | None:
        if self.n <= 0:
            return None
        return (self.wins / self.n) * 100.0

    def avg_win(self) -> float:
        return (self.sum_win / self.wins) if self.wins > 0 else 0.0

    def avg_loss(self) -> float:
        return (self.sum_loss_abs / self.losses) if self.losses > 0 else 0.0

    def breakeven_wr(self) -> float | None:
        aw = self.avg_win()
        al = self.avg_loss()
        if aw <= 0 or al <= 0:
            return None
        return (al / (al + aw)) * 100.0


class Command(BaseCommand):
    help = (
        "Minería profunda de operaciones Deriv: winrate/EV por activo/hora/tipo y "
        "recomendación de bloqueo horario."
    )

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--dias", type=int, default=14, help="Días hacia atrás (default: 14)")
        parser.add_argument("--min-muestra", type=int, default=20, help="Mínimo de trades por bucket (default: 20)")
        parser.add_argument("--tz", type=str, default="America/Bogota", help="Timezone para horas (default: America/Bogota)")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        dias = int(opts.get("dias") or 14)
        min_muestra = int(opts.get("min_muestra") or 20)
        tz = ZoneInfo(str(opts.get("tz") or "America/Bogota"))

        desde_dt = timezone.now() - timedelta(days=dias)
        desde_epoch = int(desde_dt.timestamp())

        ops = list(
            OperacionDeriv.objects.filter(
                creada_por_bot=True,
                estado="CERRADA",
                profit__isnull=False,
                opened_epoch__gte=desde_epoch,
            ).values("simbolo", "contract_type", "profit", "opened_epoch")
        )

        if not ops:
            self.stdout.write("No hay operaciones cerradas en el período.")
            return

        total = Stats()
        por_activo: dict[str, Stats] = defaultdict(Stats)
        por_tipo: dict[str, Stats] = defaultdict(Stats)
        por_hora_activo: dict[tuple[str, int], Stats] = defaultdict(Stats)

        for r in ops:
            p = float(r["profit"])
            simb = str(r.get("simbolo") or "?")
            tipo = str(r.get("contract_type") or "UNKNOWN")
            ep = int(r.get("opened_epoch") or 0)
            hr = datetime.fromtimestamp(ep, tz=tz).hour if ep else -1

            total.add(p)
            por_activo[simb].add(p)
            por_tipo[tipo].add(p)
            if hr >= 0:
                por_hora_activo[(simb, hr)].add(p)

        self.stdout.write("=" * 90)
        self.stdout.write(f"MINERÍA PROFUNDA ({dias} días) · trades={total.n}")
        self.stdout.write("=" * 90)
        self.stdout.write(
            f"Winrate={total.winrate():.2f}% | Profit={total.profit_total:.2f} | "
            f"AvgWin={total.avg_win():.3f} | AvgLoss={total.avg_loss():.3f} | "
            f"Breakeven≈{(total.breakeven_wr() or 0):.2f}%"
        )
        self.stdout.write("")

        self.stdout.write("== Por activo ==")
        for simb in sorted(por_activo.keys()):
            s = por_activo[simb]
            self.stdout.write(
                f"- {simb}: n={s.n} wr={s.winrate():.2f}% profit={s.profit_total:.2f} "
                f"breakeven≈{(s.breakeven_wr() or 0):.2f}%"
            )
        self.stdout.write("")

        self.stdout.write("== Por tipo de contrato ==")
        for tipo in sorted(por_tipo.keys()):
            s = por_tipo[tipo]
            self.stdout.write(f"- {tipo}: n={s.n} wr={s.winrate():.2f}% profit={s.profit_total:.2f}")
        self.stdout.write("")

        # Ranking horas por activo
        self.stdout.write("== Por hora (por activo) ==")
        buckets = []
        for (simb, hr), s in por_hora_activo.items():
            if s.n < min_muestra:
                continue
            buckets.append((simb, hr, s))
        buckets.sort(key=lambda x: (x[0], -(x[2].profit_total)))
        for simb, hr, s in buckets:
            self.stdout.write(
                f"- {simb} {hr:02d}:00 n={s.n} wr={s.winrate():.1f}% profit={s.profit_total:.2f}"
            )
        self.stdout.write("")

        # Recomendación bloqueo: horas con profit negativo consistente por activo
        horas_malas = set()
        for (simb, hr), s in por_hora_activo.items():
            if s.n < min_muestra:
                continue
            if s.profit_total < 0 and (s.winrate() or 0) < 50.0:
                horas_malas.add(hr)

        if horas_malas:
            rec = ",".join(str(h) for h in sorted(horas_malas))
            self.stdout.write("== Recomendación ==")
            self.stdout.write(f"- Considera bloquear horas (local): DERIV_BLOQUEO_HORAS_LOCAL={rec}")
            self.stdout.write("  (Se eligieron horas con n>=min-muestra y profit<0 + winrate<50%)")

