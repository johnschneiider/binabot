from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from gestion_riesgo.models import Cuenta


class Command(BaseCommand):
    help = "Elimina cuentas (y sus datos relacionados) que NO correspondan al DERIV_SYMBOL configurado."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--symbol", type=str, default=None, help="Símbolo a conservar (default: settings.DERIV_SYMBOL).")
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Ejecuta el borrado. Sin este flag, solo hace dry-run.",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN001
        symbol = (options.get("symbol") or getattr(settings, "DERIV_SYMBOL", "") or "").strip()
        confirmar = bool(options.get("confirmar"))
        if not symbol:
            self.stderr.write("ERROR: No se pudo determinar symbol. Pasa --symbol o define DERIV_SYMBOL.")
            return

        qs_borrar = Cuenta.objects.exclude(simbolo=symbol).order_by("id")
        qs_keep = Cuenta.objects.filter(simbolo=symbol).order_by("id")

        self.stdout.write(f"[CLEAN] symbol_conservar={symbol!r}")
        self.stdout.write(f"[CLEAN] cuentas_conservar={qs_keep.count()}  cuentas_borrar={qs_borrar.count()}")

        if qs_borrar.exists():
            self.stdout.write("[CLEAN] A borrar:")
            for c in qs_borrar.values("id", "simbolo", "balance_deriv", "updated_at"):
                self.stdout.write(f"  - {c}")

        if not confirmar:
            self.stdout.write("[CLEAN] Dry-run. Para borrar de verdad: python manage.py limpiar_cuentas --confirmar")
            return

        with transaction.atomic():
            # CASCADE borrará snapshots/operaciones relacionadas.
            borradas, _ = qs_borrar.delete()
        self.stdout.write(self.style.SUCCESS(f"[CLEAN] OK. Objetos borrados (incluyendo relacionados): {borradas}"))

