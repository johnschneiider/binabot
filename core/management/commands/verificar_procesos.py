"""
Comando para verificar el estado de los procesos y servicios del bot.
"""
import subprocess
import sys
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import ConfiguracionBot
from core.services import GestorBotCore


class Command(BaseCommand):
    help = "Verifica el estado de los procesos y servicios del bot"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("VERIFICACIÓN DE PROCESOS Y SERVICIOS"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        
        # 1. Verificar estado en la base de datos
        self.stdout.write("\n" + self.style.SUCCESS("1. ESTADO EN BASE DE DATOS"))
        gestor = GestorBotCore()
        config = gestor.configuracion
        estado = gestor.obtener_estado()
        
        self.stdout.write(f"  Estado del bot: {estado.estado}")
        self.stdout.write(f"  Balance actual: ${estado.balance_actual}")
        self.stdout.write(f"  Stop loss: ${estado.stop_loss_actual}")
        self.stdout.write(f"  En operación: {'Sí' if estado.en_operacion else 'No'}")
        
        if estado.estado == ConfiguracionBot.Estado.PAUSADO:
            self.stdout.write(self.style.WARNING(f"  ⚠️  Bot PAUSADO"))
            if estado.pausado_desde:
                self.stdout.write(f"  Pausado desde: {estado.pausado_desde}")
            if estado.pausa_finaliza:
                ahora = timezone.now()
                restante = estado.pausa_finaliza - ahora
                if restante.total_seconds() > 0:
                    horas = int(restante.total_seconds() / 3600)
                    minutos = int((restante.total_seconds() % 3600) / 60)
                    self.stdout.write(f"  Reanudación en: {horas}h {minutos}m")
                else:
                    self.stdout.write(self.style.SUCCESS("  ✅ Tiempo de pausa completado, debería reanudarse"))
        
        # 2. Verificar servicios systemd
        self.stdout.write("\n" + self.style.SUCCESS("2. SERVICIOS SYSTEMD"))
        servicios = [
            "binabot-loop.service",
            "binabot-ticks.service",
            "binabot.service",
        ]
        
        for servicio in servicios:
            try:
                resultado = subprocess.run(
                    ["systemctl", "is-active", servicio],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                estado_servicio = resultado.stdout.strip()
                if estado_servicio == "active":
                    self.stdout.write(self.style.SUCCESS(f"  ✅ {servicio}: ACTIVO"))
                elif estado_servicio == "inactive":
                    self.stdout.write(self.style.WARNING(f"  ⚠️  {servicio}: INACTIVO"))
                elif estado_servicio == "failed":
                    self.stdout.write(self.style.ERROR(f"  ❌ {servicio}: FALLIDO"))
                else:
                    self.stdout.write(f"  ⚠️  {servicio}: {estado_servicio}")
                
                # Verificar si está habilitado
                resultado_enabled = subprocess.run(
                    ["systemctl", "is-enabled", servicio],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                enabled = resultado_enabled.stdout.strip()
                if enabled == "enabled":
                    self.stdout.write(f"    (Habilitado al inicio)")
                elif enabled == "disabled":
                    self.stdout.write(self.style.WARNING(f"    (NO habilitado al inicio)"))
                    
            except subprocess.TimeoutExpired:
                self.stdout.write(self.style.ERROR(f"  ❌ {servicio}: Timeout al verificar"))
            except FileNotFoundError:
                self.stdout.write(self.style.ERROR(f"  ❌ systemctl no encontrado (¿estás en Windows?)"))
                break
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ {servicio}: Error - {e}"))
        
        # 3. Verificar procesos Python
        self.stdout.write("\n" + self.style.SUCCESS("3. PROCESOS PYTHON"))
        try:
            resultado = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            procesos = resultado.stdout
            procesos_bot = [p for p in procesos.split("\n") if "ejecutar_bot" in p or "manage.py" in p]
            
            if procesos_bot:
                self.stdout.write(f"  Encontrados {len(procesos_bot)} proceso(s) del bot:")
                for proceso in procesos_bot[:5]:  # Mostrar máximo 5
                    partes = proceso.split()
                    if len(partes) > 1:
                        pid = partes[1]
                        cmd = " ".join(partes[10:])[:80]  # Comando truncado
                        self.stdout.write(f"    PID {pid}: {cmd}")
            else:
                self.stdout.write(self.style.WARNING("  ⚠️  No se encontraron procesos del bot ejecutándose"))
                
        except FileNotFoundError:
            # En Windows, ps no existe, usar tasklist
            try:
                resultado = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq python.exe"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "python.exe" in resultado.stdout:
                    self.stdout.write("  ✅ Procesos Python encontrados (Windows)")
                else:
                    self.stdout.write(self.style.WARNING("  ⚠️  No se encontraron procesos Python"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ Error verificando procesos: {e}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Error: {e}"))
        
        # 4. Resumen
        self.stdout.write("\n" + self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("RESUMEN"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        
        if estado.estado == ConfiguracionBot.Estado.PAUSADO:
            self.stdout.write(self.style.WARNING("⚠️  El bot está PAUSADO en la base de datos."))
            self.stdout.write("   Esto puede ser porque:")
            self.stdout.write("   - Se alcanzó el stop loss")
            self.stdout.write("   - Fue pausado manualmente")
            self.stdout.write("   - Está esperando el mejor horario para reanudar")
        elif estado.estado == ConfiguracionBot.Estado.OPERANDO:
            self.stdout.write(self.style.SUCCESS("✅ El bot está OPERANDO en la base de datos."))
            if estado.en_operacion:
                self.stdout.write("   ⏸️  Actualmente tiene una operación en curso.")
            else:
                self.stdout.write("   ✅ Listo para ejecutar operaciones.")
        
        self.stdout.write("\n" + self.style.SUCCESS("Para reiniciar los servicios:"))
        self.stdout.write("  sudo systemctl restart binabot-loop.service")
        self.stdout.write("  sudo systemctl restart binabot-ticks.service")

