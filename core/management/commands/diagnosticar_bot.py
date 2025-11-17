"""
Comando para diagnosticar por qué el bot no está operando.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import ActivoPermitido
from core.services import GestorBotCore
from historial.models import Tick
from trading.database.cache_manager import obtener_ticks_cache
from trading.models import IndicadoresActivo
from trading.ranking import calcular_score_activo


class Command(BaseCommand):
    help = "Diagnostica por qué el bot no está operando"

    def handle(self, *args, **options):
        gestor = GestorBotCore()
        config = gestor.configuracion

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("DIAGNÓSTICO DEL BOT"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")

        # 1. Verificar estado del bot
        self.stdout.write("1. ESTADO DEL BOT:")
        self.stdout.write("-" * 80)
        self.stdout.write(f"Estado: {config.estado}")
        self.stdout.write(f"En operación: {config.en_operacion}")
        if config.estado != config.Estado.OPERANDO:
            self.stdout.write(
                self.style.ERROR(f"❌ Bot NO está en estado OPERANDO (está: {config.estado})")
            )
        else:
            self.stdout.write(self.style.SUCCESS("✓ Bot está en estado OPERANDO"))
        if config.en_operacion:
            self.stdout.write(
                self.style.WARNING("⚠️  Hay una operación marcada como en curso")
            )
        self.stdout.write("")

        # 2. Verificar balance y objetivos
        self.stdout.write("2. BALANCE Y OBJETIVOS:")
        self.stdout.write("-" * 80)
        self.stdout.write(f"Balance actual: US$ {config.balance_actual}")
        self.stdout.write(f"Meta actual: US$ {config.meta_actual}")
        self.stdout.write(f"Stop loss actual: US$ {config.stop_loss_actual}")
        if config.stop_loss_actual <= 0 or config.meta_actual <= 0:
            self.stdout.write(
                self.style.ERROR("❌ Balance/objetivos no configurados correctamente")
            )
        else:
            self.stdout.write(self.style.SUCCESS("✓ Balance y objetivos configurados"))
        self.stdout.write("")

        # 3. Verificar activos habilitados
        self.stdout.write("3. ACTIVOS HABILITADOS:")
        self.stdout.write("-" * 80)
        activos = ActivoPermitido.objects.filter(habilitado=True)
        total_activos = activos.count()
        self.stdout.write(f"Total activos habilitados: {total_activos}")
        if total_activos == 0:
            self.stdout.write(
                self.style.ERROR("❌ No hay activos habilitados para operar")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"✓ Hay {total_activos} activos habilitados"))
            # Mostrar primeros 5
            for activo in activos[:5]:
                self.stdout.write(f"  - {activo.nombre}")
        self.stdout.write("")

        # 4. Verificar ticks disponibles
        self.stdout.write("4. TICKS DISPONIBLES:")
        self.stdout.write("-" * 80)
        total_ticks = Tick.objects.count()
        ticks_recientes = Tick.objects.filter(
            epoch__gte=timezone.now() - timezone.timedelta(hours=1)
        ).count()
        self.stdout.write(f"Total ticks en BD: {total_ticks}")
        self.stdout.write(f"Ticks últimos 60 min: {ticks_recientes}")
        if ticks_recientes == 0:
            self.stdout.write(
                self.style.ERROR("❌ No hay ticks recientes (recolector puede estar detenido)")
            )
        else:
            self.stdout.write(self.style.SUCCESS("✓ Hay ticks recientes"))
        self.stdout.write("")

        # 5. Verificar indicadores y scores
        self.stdout.write("5. INDICADORES Y SCORES:")
        self.stdout.write("-" * 80)
        if total_activos > 0:
            activos_con_indicadores = 0
            activos_con_score_alto = 0
            mejor_score = Decimal("0.00")
            mejor_activo = None

            for activo in activos[:10]:  # Revisar primeros 10
                try:
                    indicadores = IndicadoresActivo.objects.filter(activo=activo).first()
                    if indicadores:
                        activos_con_indicadores += 1
                        score = indicadores.score_total
                        if score > mejor_score:
                            mejor_score = score
                            mejor_activo = activo.nombre
                        if score >= Decimal("40.00"):
                            activos_con_score_alto += 1
                except Exception:
                    pass

            self.stdout.write(f"Activos con indicadores calculados: {activos_con_indicadores}")
            self.stdout.write(f"Activos con score >= 40: {activos_con_score_alto}")
            self.stdout.write(f"Mejor score encontrado: {mejor_score} ({mejor_activo or 'N/A'})")
            
            if mejor_score < Decimal("40.00"):
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠️  Score máximo ({mejor_score}) no alcanza el umbral mínimo (40.00)"
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS("✓ Hay activos con score suficiente"))
        else:
            self.stdout.write(self.style.WARNING("⚠️  No hay activos para evaluar"))
        self.stdout.write("")

        # 6. Verificar cooldowns activos
        self.stdout.write("6. COOLDOWNS ACTIVOS:")
        self.stdout.write("-" * 80)
        from trading.models import CooldownActivo
        cooldowns = CooldownActivo.objects.filter(
            finaliza_en__gt=timezone.now()
        )
        total_cooldowns = cooldowns.count()
        self.stdout.write(f"Cooldowns activos: {total_cooldowns}")
        if total_cooldowns > 0:
            for cooldown in cooldowns[:5]:
                self.stdout.write(
                    f"  - {cooldown.activo.nombre}: {cooldown.motivo} (hasta {cooldown.finaliza_en})"
                )
        self.stdout.write("")

        # 7. Verificar límites de operaciones
        self.stdout.write("7. LÍMITES DE OPERACIONES:")
        self.stdout.write("-" * 80)
        from historial.models import Operacion
        from trading.risk import verificar_limites_activo
        
        if total_activos > 0:
            activo_ejemplo = activos.first()
            puede_operar = verificar_limites_activo(activo_ejemplo.nombre)
            self.stdout.write(f"¿Puede operar {activo_ejemplo.nombre}? {puede_operar}")
            if not puede_operar:
                self.stdout.write(
                    self.style.WARNING("⚠️  Límite de operaciones por ciclo alcanzado")
                )
        self.stdout.write("")

        # 8. Verificar token de API
        self.stdout.write("8. CONFIGURACIÓN DE API:")
        self.stdout.write("-" * 80)
        from django.conf import settings
        tiene_token = bool(settings.DERIV_API_TOKEN)
        tiene_app_id = bool(settings.DERIV_APP_ID)
        self.stdout.write(f"Token configurado: {tiene_token}")
        self.stdout.write(f"App ID configurado: {tiene_app_id}")
        if not tiene_token or not tiene_app_id:
            self.stdout.write(
                self.style.ERROR("❌ Token o App ID no configurados")
            )
        else:
            self.stdout.write(self.style.SUCCESS("✓ API configurada"))
        self.stdout.write("")

        # 9. Resumen y recomendaciones
        self.stdout.write("=" * 80)
        self.stdout.write("RESUMEN:")
        self.stdout.write("=" * 80)
        
        problemas = []
        if config.estado != config.Estado.OPERANDO:
            problemas.append("Bot no está en estado OPERANDO")
        if config.en_operacion:
            problemas.append("Hay una operación marcada como en curso")
        if config.stop_loss_actual <= 0 or config.meta_actual <= 0:
            problemas.append("Balance/objetivos no configurados")
        if total_activos == 0:
            problemas.append("No hay activos habilitados")
        if ticks_recientes == 0:
            problemas.append("No hay ticks recientes (recolector puede estar detenido)")
        if mejor_score < Decimal("40.00") and total_activos > 0:
            problemas.append(f"Score máximo ({mejor_score}) no alcanza umbral mínimo (40.00)")
        if not tiene_token or not tiene_app_id:
            problemas.append("Token o App ID no configurados")

        if problemas:
            self.stdout.write(self.style.ERROR("PROBLEMAS ENCONTRADOS:"))
            for problema in problemas:
                self.stdout.write(self.style.ERROR(f"  ❌ {problema}"))
        else:
            self.stdout.write(
                self.style.SUCCESS("✓ No se encontraron problemas obvios")
            )
            self.stdout.write(
                self.style.WARNING(
                    "Si aún no opera, puede ser que no haya señales válidas en este momento."
                )
            )

        self.stdout.write("")
        self.stdout.write("Para ver logs en tiempo real:")
        self.stdout.write("  journalctl -u binabot-loop.service -f")

