"""
Comando para diagnosticar la sincronización entre WebSocket, balance y operaciones.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from core.models import ConfiguracionBot
from core.services import GestorBotCore
from historial.models import Operacion
from datetime import timedelta


class Command(BaseCommand):
    help = "Diagnostica la sincronización entre WebSocket, balance y operaciones"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("DIAGNÓSTICO DE SINCRONIZACIÓN WEBSOCKET"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        
        gestor = GestorBotCore()
        config = gestor.configuracion
        
        # 1. Verificar balance actual
        self.stdout.write("\n" + self.style.SUCCESS("1. BALANCE Y CONFIGURACIÓN"))
        self.stdout.write(f"  Balance actual en BD: ${config.balance_actual}")
        self.stdout.write(f"  Estado: {config.estado}")
        self.stdout.write(f"  En operación: {config.en_operacion}")
        
        # Sincronizar con Deriv
        try:
            gestor.sincronizar_balance_desde_api()
            config.refresh_from_db()
            self.stdout.write(f"  Balance después de sincronizar: ${config.balance_actual}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Error al sincronizar: {e}"))
        
        # 2. Verificar operaciones recientes
        self.stdout.write("\n" + self.style.SUCCESS("2. OPERACIONES RECIENTES (Últimas 10)"))
        
        ahora = timezone.now()
        ultimas_24h = ahora - timedelta(hours=24)
        operaciones_recientes = Operacion.objetos.reales().filter(
            hora_inicio__gte=ultimas_24h
        ).order_by('-hora_inicio')[:10]
        
        if operaciones_recientes:
            self.stdout.write(f"  Total operaciones en últimas 24h: {operaciones_recientes.count()}")
            
            total_beneficio = Decimal("0.00")
            for op in operaciones_recientes:
                resultado_emoji = "✅" if op.resultado == Operacion.Resultado.GANADA else "❌"
                self.stdout.write(
                    f"    {resultado_emoji} {op.hora_inicio.strftime('%Y-%m-%d %H:%M:%S')} - "
                    f"{op.activo} {op.direccion} - "
                    f"Beneficio: ${op.beneficio} - "
                    f"Contrato: {op.numero_contrato}"
                )
                total_beneficio += op.beneficio
            
            self.stdout.write(f"\n  Beneficio total de últimas operaciones: ${total_beneficio}")
        else:
            self.stdout.write(self.style.WARNING("  ⚠️  No hay operaciones en las últimas 24 horas"))
        
        # 3. Verificar balance esperado vs real
        self.stdout.write("\n" + self.style.SUCCESS("3. VERIFICACIÓN DE BALANCE"))
        
        # Calcular balance esperado desde operaciones
        balance_esperado = gestor.calcular_balance_esperado_desde_operaciones()
        balance_real = config.balance_actual
        
        self.stdout.write(f"  Balance esperado (desde operaciones): ${balance_esperado}")
        self.stdout.write(f"  Balance real (en BD): ${balance_real}")
        
        diferencia = balance_real - balance_esperado
        if abs(diferencia) <= Decimal("0.01"):
            self.stdout.write(self.style.SUCCESS("  ✅ Balance sincronizado correctamente"))
        else:
            self.stdout.write(self.style.WARNING(
                f"  ⚠️  Diferencia: ${diferencia}"
            ))
            self.stdout.write(self.style.WARNING(
                "     Esto puede deberse a:"
            ))
            self.stdout.write(self.style.WARNING(
                "     - Comisiones o fees no contabilizados"
            ))
            self.stdout.write(self.style.WARNING(
                "     - Ajustes manuales en Deriv"
            ))
            self.stdout.write(self.style.WARNING(
                "     - Operaciones que no se registraron en BD"
            ))
        
        # 4. Verificar operaciones sin contract_id válido
        self.stdout.write("\n" + self.style.SUCCESS("4. VERIFICACIÓN DE OPERACIONES VÁLIDAS"))
        
        # Buscar operaciones con IDs sospechosos (PEND-)
        operaciones_pend = Operacion.objetos.reales().filter(
            numero_contrato__startswith="PEND-"
        )
        
        if operaciones_pend.exists():
            self.stdout.write(self.style.ERROR(
                f"  ❌ Encontradas {operaciones_pend.count()} operaciones con ID PEND-"
            ))
            self.stdout.write(self.style.ERROR(
                "     Estas operaciones NO deberían existir (no tienen contract_id válido de Deriv)"
            ))
            self.stdout.write(self.style.WARNING(
                "     Recomendación: Eliminar estas operaciones o revisar por qué se crearon"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "  ✅ No hay operaciones con ID PEND- (todas tienen contract_id válido)"
            ))
        
        # 5. Verificar última operación
        self.stdout.write("\n" + self.style.SUCCESS("5. ÚLTIMA OPERACIÓN"))
        
        ultima_operacion = Operacion.objetos.reales().order_by('-hora_inicio').first()
        
        if ultima_operacion:
            self.stdout.write(f"  Última operación:")
            self.stdout.write(f"    Contrato: {ultima_operacion.numero_contrato}")
            self.stdout.write(f"    Activo: {ultima_operacion.activo}")
            self.stdout.write(f"    Dirección: {ultima_operacion.direccion}")
            self.stdout.write(f"    Resultado: {ultima_operacion.resultado}")
            self.stdout.write(f"    Beneficio: ${ultima_operacion.beneficio}")
            self.stdout.write(f"    Hora inicio: {ultima_operacion.hora_inicio}")
            self.stdout.write(f"    Hora fin: {ultima_operacion.hora_fin}")
            self.stdout.write(f"    Es simulada: {ultima_operacion.es_simulada}")
            
            tiempo_desde = ahora - ultima_operacion.hora_inicio
            minutos = int(tiempo_desde.total_seconds() / 60)
            self.stdout.write(f"    Hace: {minutos} minutos")
        else:
            self.stdout.write(self.style.WARNING("  ⚠️  No hay operaciones registradas"))
        
        # 6. Verificar eventos WebSocket
        self.stdout.write("\n" + self.style.SUCCESS("6. VERIFICACIÓN DE WEBSOCKET"))
        
        try:
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            
            if channel_layer:
                self.stdout.write(self.style.SUCCESS("  ✅ Channel layer configurado"))
                self.stdout.write(f"    Backend: {channel_layer.__class__.__name__}")
            else:
                self.stdout.write(self.style.ERROR("  ❌ Channel layer NO configurado"))
                self.stdout.write(self.style.ERROR(
                    "     Los eventos WebSocket no se pueden enviar"
                ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Error al verificar channel layer: {e}"))
        
        # 7. Resumen y recomendaciones
        self.stdout.write("\n" + self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("RESUMEN Y RECOMENDACIONES"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        
        problemas = []
        
        if abs(diferencia) > Decimal("1.00"):
            problemas.append("⚠️  Diferencia significativa entre balance esperado y real")
        
        if operaciones_pend.exists():
            problemas.append("❌ Hay operaciones con ID PEND- (no válidas)")
        
        if not channel_layer:
            problemas.append("❌ Channel layer no configurado (WebSocket no funciona)")
        
        if problemas:
            self.stdout.write(self.style.WARNING("\n⚠️  PROBLEMAS DETECTADOS:"))
            for problema in problemas:
                self.stdout.write(f"  {problema}")
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ TODO PARECE ESTAR FUNCIONANDO CORRECTAMENTE"))
        
        self.stdout.write("\n" + self.style.SUCCESS("Para verificar en tiempo real:"))
        self.stdout.write("  1. Observa los logs del bot:")
        self.stdout.write("     journalctl -u binabot-loop.service -f")
        self.stdout.write("  2. Abre la consola del navegador (F12) y verifica:")
        self.stdout.write("     - Conexiones WebSocket activas")
        self.stdout.write("     - Eventos recibidos")
        self.stdout.write("     - Errores de red")
        self.stdout.write("  3. Verifica que las operaciones aparezcan en:")
        self.stdout.write("     /api/dashboard/historicos/")

