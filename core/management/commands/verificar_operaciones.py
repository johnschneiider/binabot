from django.core.management.base import BaseCommand
from django.utils import timezone
from historial.models import Operacion
from core.models import ConfiguracionBot


class Command(BaseCommand):
    help = "Verifica el estado de las operaciones en la base de datos"

    def handle(self, *args, **options):
        config = ConfiguracionBot.objects.first()
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write("ESTADO DEL BOT")
        self.stdout.write("="*80)
        if config:
            self.stdout.write(f"Estado: {config.estado}")
            self.stdout.write(f"Balance actual: {config.balance_actual}")
            self.stdout.write(f"En operación: {config.en_operacion}")
            self.stdout.write(f"Activo seleccionado: {config.activo_seleccionado}")
        else:
            self.stdout.write(self.style.ERROR("No hay configuración del bot"))
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write("OPERACIONES REALES (es_simulada=False)")
        self.stdout.write("="*80)
        operaciones_reales = Operacion.objetos.reales()
        total_reales = operaciones_reales.count()
        self.stdout.write(f"Total de operaciones reales: {total_reales}")
        
        if total_reales > 0:
            self.stdout.write("\nÚltimas 10 operaciones reales:")
            self.stdout.write("-" * 80)
            for op in operaciones_reales[:10]:
                self.stdout.write(
                    f"ID: {op.id} | Contrato: {op.numero_contrato} | "
                    f"Activo: {op.activo} | Dirección: {op.direccion} | "
                    f"Resultado: {op.resultado} | Beneficio: {op.beneficio} | "
                    f"Simulada: {op.es_simulada} | Hora: {op.hora_inicio}"
                )
        else:
            self.stdout.write(self.style.WARNING("No hay operaciones reales registradas"))
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write("TODAS LAS OPERACIONES (sin filtro)")
        self.stdout.write("="*80)
        todas = Operacion.objects.all()
        total_todas = todas.count()
        self.stdout.write(f"Total de operaciones (todas): {total_todas}")
        
        if total_todas > 0:
            simuladas = todas.filter(es_simulada=True).count()
            reales = todas.filter(es_simulada=False).count()
            self.stdout.write(f"  - Reales: {reales}")
            self.stdout.write(f"  - Simuladas: {simuladas}")
            
            self.stdout.write("\nÚltimas 10 operaciones (todas):")
            self.stdout.write("-" * 80)
            for op in todas[:10]:
                self.stdout.write(
                    f"ID: {op.id} | Contrato: {op.numero_contrato} | "
                    f"Activo: {op.activo} | Dirección: {op.direccion} | "
                    f"Resultado: {op.resultado} | Beneficio: {op.beneficio} | "
                    f"Simulada: {op.es_simulada} | Hora: {op.hora_inicio}"
                )
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write("OPERACIONES PENDIENTES")
        self.stdout.write("="*80)
        pendientes = Operacion.objects.filter(resultado=Operacion.Resultado.PENDIENTE)
        total_pendientes = pendientes.count()
        self.stdout.write(f"Total de operaciones pendientes: {total_pendientes}")
        
        if total_pendientes > 0:
            self.stdout.write("\nOperaciones pendientes:")
            self.stdout.write("-" * 80)
            for op in pendientes:
                self.stdout.write(
                    f"ID: {op.id} | Contrato: {op.numero_contrato} | "
                    f"Activo: {op.activo} | Dirección: {op.direccion} | "
                    f"Simulada: {op.es_simulada} | Hora inicio: {op.hora_inicio} | "
                    f"Hora fin: {op.hora_fin}"
                )
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write("ESTADÍSTICAS")
        self.stdout.write("="*80)
        if total_reales > 0:
            ganadas = operaciones_reales.ganadas().count()
            perdidas = operaciones_reales.perdidas().count()
            winrate = (ganadas / total_reales * 100) if total_reales > 0 else 0
            self.stdout.write(f"Ganadas: {ganadas}")
            self.stdout.write(f"Perdidas: {perdidas}")
            self.stdout.write(f"Winrate: {winrate:.2f}%")
        
        self.stdout.write("\n")

