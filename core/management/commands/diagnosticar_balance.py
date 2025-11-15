from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.services import GestorBotCore
from historial.models import AjusteBalance, Operacion


class Command(BaseCommand):
    help = "Diagnostica discrepancias entre el balance real y el balance esperado desde operaciones."

    def add_arguments(self, parser):
        parser.add_argument(
            "--detallado",
            action="store_true",
            help="Muestra información detallada de operaciones y ajustes",
        )

    def handle(self, *args, **options):
        gestor = GestorBotCore()
        config = gestor.configuracion
        detallado = options["detallado"]

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("DIAGNÓSTICO DE BALANCE"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")

        # Obtener balance real desde API
        try:
            from integracion_deriv.client import obtener_balance_sync

            respuesta = obtener_balance_sync()
            balance_info = respuesta.get("balance", {})
            balance_real = Decimal(str(balance_info.get("balance", "0")))
        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(f"Error al obtener balance de Deriv: {exc}")
            )
            balance_real = config.balance_actual
            self.stdout.write(
                self.style.WARNING(f"Usando balance almacenado: {balance_real}")
            )

        # Estadísticas de operaciones
        operaciones_reales = Operacion.objetos.reales().exclude(
            resultado=Operacion.Resultado.PENDIENTE
        )
        total_operaciones = operaciones_reales.count()
        operaciones_ganadas = operaciones_reales.filter(
            resultado=Operacion.Resultado.GANADA
        ).count()
        operaciones_perdidas = operaciones_reales.filter(
            resultado=Operacion.Resultado.PERDIDA
        ).count()
        total_beneficios = sum(op.beneficio for op in operaciones_reales)

        # Calcular balance esperado (método actual)
        balance_esperado = gestor.calcular_balance_esperado_desde_operaciones()
        
        # Calcular balance inicial real (método alternativo: retroceder desde balance actual)
        balance_inicial_calculado = (balance_real - total_beneficios).quantize(Decimal("0.01"))
        
        # Obtener balance inicial usado en el cálculo
        balance_inicial_usado = (
            config.balance_meta_base
            if config.balance_meta_base > 0
            else config.balance_actual
        )

        # Mostrar información básica
        self.stdout.write(self.style.SUCCESS("INFORMACIÓN DE BALANCE"))
        self.stdout.write("-" * 80)
        self.stdout.write(f"Balance actual (almacenado):     US$ {config.balance_actual:,.2f}")
        self.stdout.write(f"Balance real (desde Deriv API):   US$ {balance_real:,.2f}")
        self.stdout.write(f"Balance esperado (desde ops):     US$ {balance_esperado:,.2f}")
        self.stdout.write("")
        
        # Información de cálculo
        self.stdout.write(self.style.SUCCESS("CÁLCULO DEL BALANCE ESPERADO"))
        self.stdout.write("-" * 80)
        self.stdout.write(f"Balance inicial usado:            US$ {balance_inicial_usado:,.2f}")
        self.stdout.write(f"  (balance_meta_base: {config.balance_meta_base:,.2f})")
        self.stdout.write(f"Total beneficios operaciones:      US$ {total_beneficios:,.2f}")
        self.stdout.write(f"Balance esperado = {balance_inicial_usado:,.2f} + {total_beneficios:,.2f} = {balance_esperado:,.2f}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("CÁLCULO ALTERNATIVO (RETROCESO)"))
        self.stdout.write("-" * 80)
        self.stdout.write(f"Balance inicial calculado:         US$ {balance_inicial_calculado:,.2f}")
        self.stdout.write(f"  (Balance real - Total beneficios = {balance_real:,.2f} - {total_beneficios:,.2f})")
        diferencia_inicial = balance_inicial_usado - balance_inicial_calculado
        if abs(diferencia_inicial) > Decimal("0.01"):
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  Diferencia en balance inicial: US$ {diferencia_inicial:,.2f}"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    "   Esto sugiere que el balance_meta_base no es el balance inicial real,"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    "   o que hubo operaciones antes de que se inicializara el tracking."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("✓ Balance inicial consistente")
            )
        self.stdout.write("")

        diferencia = balance_real - balance_esperado
        if abs(diferencia) > Decimal("0.01"):
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  DISCREPANCIA DETECTADA: US$ {diferencia:,.2f}"
                )
            )
            if diferencia < 0:
                self.stdout.write(
                    self.style.ERROR(
                        f"   El balance real es MENOR que el esperado. "
                        f"Se han perdido {abs(diferencia):,.2f} sin operaciones registradas."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"   El balance real es MAYOR que el esperado. "
                        f"Diferencia positiva de {diferencia:,.2f}."
                    )
                )
        else:
            self.stdout.write(
                self.style.SUCCESS("✓ Balance consistente (sin discrepancias significativas)")
            )
        self.stdout.write("")

        # Estadísticas de operaciones
        self.stdout.write(self.style.SUCCESS("ESTADÍSTICAS DE OPERACIONES"))
        self.stdout.write("-" * 80)
        self.stdout.write(f"Total operaciones reales:         {total_operaciones}")
        self.stdout.write(f"  - Ganadas:                      {operaciones_ganadas}")
        self.stdout.write(f"  - Perdidas:                     {operaciones_perdidas}")
        self.stdout.write(f"Total beneficios acumulados:       US$ {total_beneficios:,.2f}")
        self.stdout.write("")

        # Ajustes registrados
        ajustes = AjusteBalance.objects.all().order_by("-detectado_en")[:10]
        if ajustes.exists():
            self.stdout.write(self.style.SUCCESS("AJUSTES DE BALANCE REGISTRADOS (últimos 10)"))
            self.stdout.write("-" * 80)
            for ajuste in ajustes:
                fecha_str = ajuste.detectado_en.strftime("%Y-%m-%d %H:%M:%S")
                if ajuste.diferencia < 0:
                    estilo = self.style.ERROR
                    simbolo = "↓"
                else:
                    estilo = self.style.SUCCESS
                    simbolo = "↑"
                self.stdout.write(
                    estilo(
                        f"{simbolo} {fecha_str}: Diferencia de US$ {ajuste.diferencia:,.2f} "
                        f"(Real: {ajuste.balance_real:,.2f}, Esperado: {ajuste.balance_esperado:,.2f})"
                    )
                )
                if detallado and ajuste.descripcion:
                    self.stdout.write(f"   {ajuste.descripcion}")
            self.stdout.write("")

        # Información detallada si se solicita
        if detallado:
            self.stdout.write(self.style.SUCCESS("ÚLTIMAS OPERACIONES REALES (últimas 10)"))
            self.stdout.write("-" * 80)
            ultimas_ops = operaciones_reales[:10]
            for op in ultimas_ops:
                fecha_str = op.hora_inicio.strftime("%Y-%m-%d %H:%M:%S")
                resultado_str = "GANADA" if op.es_ganada else "PERDIDA"
                estilo = self.style.SUCCESS if op.es_ganada else self.style.ERROR
                self.stdout.write(
                    estilo(
                        f"{fecha_str} | {op.activo} {op.direccion} | "
                        f"{resultado_str} | Beneficio: US$ {op.beneficio:,.2f}"
                    )
                )
            self.stdout.write("")

        # Resumen final
        self.stdout.write(self.style.SUCCESS("RESUMEN"))
        self.stdout.write("-" * 80)
        if abs(diferencia) > Decimal("0.01"):
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  Se detectó una discrepancia. Esto puede deberse a:\n"
                    "   - Comisiones o fees de Deriv no contabilizados\n"
                    "   - Ajustes manuales en la cuenta\n"
                    "   - Operaciones ejecutadas fuera del bot\n"
                    "   - Errores en el registro de operaciones\n"
                    "   - Balance inicial (balance_meta_base) incorrecto"
                )
            )
            self.stdout.write("")
            self.stdout.write(
                "   Los ajustes se registran automáticamente en la tabla AjusteBalance."
            )
            self.stdout.write("")
            if abs(diferencia_inicial) > Decimal("0.01"):
                self.stdout.write(
                    self.style.WARNING(
                        "💡 RECOMENDACIÓN: El balance inicial usado puede ser incorrecto.\n"
                        f"   Balance inicial usado: {balance_inicial_usado:,.2f}\n"
                        f"   Balance inicial calculado (retroceso): {balance_inicial_calculado:,.2f}\n"
                        "   Considera reinicializar el balance con el valor correcto."
                    )
                )
        else:
            self.stdout.write(
                self.style.SUCCESS("✓ Todo parece estar en orden. No hay discrepancias significativas.")
            )

