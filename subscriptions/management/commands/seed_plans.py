from django.core.management.base import BaseCommand
from subscriptions.models import Plan


class Command(BaseCommand):
    help = "Crea los planes iniciales de suscripcion"

    def handle(self, *args, **options):
        plans_data = [
            {
                "nombre": "Free",
                "slug": "free",
                "tipo": Plan.TipoPlan.FREE,
                "max_cuentas_deriv": 1,
                "max_symbols": 1,
                "permite_backtest": False,
                "permite_api": False,
                "permite_white_label": False,
                "soporte_prioritario": False,
                "max_trades_dia": 10,
                "max_ticks_por_dia": 1000,
                "precio_mensual": 0,
                "precio_trimestral": 0,
                "precio_anual": 0,
                "orden": 0,
                "dias_trial": 7,
                "descripcion": "Plan gratuito para probar el sistema. Ideal para usuarios nuevos.",
            },
            {
                "nombre": "Basico",
                "slug": "basico",
                "tipo": Plan.TipoPlan.BASICO,
                "max_cuentas_deriv": 3,
                "max_symbols": 3,
                "permite_backtest": False,
                "permite_api": False,
                "permite_white_label": False,
                "soporte_prioritario": False,
                "max_trades_dia": 50,
                "max_ticks_por_dia": 10000,
                "precio_mensual": 29,
                "precio_trimestral": 79,
                "precio_anual": 249,
                "orden": 1,
                "dias_trial": 3,
                "descripcion": "Plan basico para traders individuales. Incluye hasta 3 cuentas de trading.",
            },
            {
                "nombre": "Pro",
                "slug": "pro",
                "tipo": Plan.TipoPlan.PRO,
                "max_cuentas_deriv": 10,
                "max_symbols": 10,
                "permite_backtest": True,
                "permite_api": True,
                "permite_white_label": False,
                "soporte_prioritario": True,
                "max_trades_dia": 200,
                "max_ticks_por_dia": 50000,
                "precio_mensual": 79,
                "precio_trimestral": 199,
                "precio_anual": 599,
                "orden": 2,
                "dias_trial": 3,
                "descripcion": "Plan profesional con acceso a API, backtesting y soporte prioritario.",
            },
            {
                "nombre": "Institucional",
                "slug": "institucional",
                "tipo": Plan.TipoPlan.INSTITUCIONAL,
                "max_cuentas_deriv": 999,
                "max_symbols": 999,
                "permite_backtest": True,
                "permite_api": True,
                "permite_white_label": True,
                "soporte_prioritario": True,
                "max_trades_dia": 99999,
                "max_ticks_por_dia": 999999,
                "precio_mensual": 199,
                "precio_trimestral": 499,
                "precio_anual": 1499,
                "orden": 3,
                "dias_trial": 0,
                "descripcion": "Plan institucional con acceso completo, white label y soporte 24/7.",
            },
        ]
        
        created_count = 0
        updated_count = 0
        
        for plan_data in plans_data:
            plan, created = Plan.objects.update_or_create(
                slug=plan_data["slug"],
                defaults=plan_data
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Creado: {plan.nombre}")
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(f"Actualizado: {plan.nombre}")
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nProceso completado: {created_count} creados, {updated_count} actualizados."
            )
        )
