"""
Servicio para verificar el estado de los servicios systemd del bot.
"""
import subprocess
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class EstadoServiciosService:
    """
    Verifica el estado de los servicios systemd relacionados con el bot.
    """
    
    SERVICIOS = {
        "bot_principal": "binabot-loop.service",
        "recolector_ticks": "binabot-ticks.service",
        "servidor_web": "binabot.service",
        "dashboard_updates": "binabot-dashboard.service",
    }
    
    @staticmethod
    def verificar_servicio(nombre_servicio: str) -> Dict[str, any]:
        """
        Verifica el estado de un servicio systemd.
        
        Returns:
            Dict con:
            - activo: bool - Si el servicio está corriendo
            - estado: str - Estado del servicio (active, inactive, failed, etc.)
            - habilitado: bool - Si está habilitado para inicio automático
            - ultima_actualizacion: datetime - Timestamp de la verificación
            - error: str - Mensaje de error si hubo problema
        """
        resultado = {
            "activo": False,
            "estado": "unknown",
            "habilitado": False,
            "ultima_actualizacion": datetime.now().isoformat(),
            "error": None,
        }
        
        try:
            # Verificar si el servicio está activo
            proceso = subprocess.run(
                ["systemctl", "is-active", nombre_servicio],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if proceso.returncode == 0:
                estado_activo = proceso.stdout.strip()
                resultado["activo"] = estado_activo == "active"
                resultado["estado"] = estado_activo
            else:
                resultado["estado"] = "inactive"
                resultado["error"] = proceso.stderr.strip() or "Servicio no encontrado o inactivo"
            
            # Verificar si está habilitado
            proceso_habilitado = subprocess.run(
                ["systemctl", "is-enabled", nombre_servicio],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if proceso_habilitado.returncode == 0:
                resultado["habilitado"] = proceso_habilitado.stdout.strip() == "enabled"
            
        except subprocess.TimeoutExpired:
            resultado["error"] = "Timeout al verificar el servicio"
            logger.warning(f"Timeout al verificar servicio {nombre_servicio}")
        except FileNotFoundError:
            resultado["error"] = "systemctl no encontrado (no es un sistema systemd)"
            logger.warning("systemctl no encontrado - probablemente no es un sistema systemd")
        except Exception as e:
            resultado["error"] = str(e)
            logger.error(f"Error al verificar servicio {nombre_servicio}: {e}", exc_info=True)
        
        return resultado
    
    @staticmethod
    def verificar_todos_servicios() -> Dict[str, Dict[str, any]]:
        """
        Verifica el estado de todos los servicios del bot.
        
        Returns:
            Dict con el estado de cada servicio
        """
        estados = {}
        
        for clave, nombre_servicio in EstadoServiciosService.SERVICIOS.items():
            estados[clave] = EstadoServiciosService.verificar_servicio(nombre_servicio)
        
        return estados
    
    @staticmethod
    def verificar_recolector_ticks_activo() -> bool:
        """
        Verifica específicamente si el recolector de ticks está activo.
        También verifica si hay ticks recientes en la base de datos como respaldo.
        """
        from historial.models import Tick
        from django.utils import timezone
        
        # Primero verificar el servicio
        estado_servicio = EstadoServiciosService.verificar_servicio(
            EstadoServiciosService.SERVICIOS["recolector_ticks"]
        )
        
        if estado_servicio["activo"]:
            return True
        
        # Si el servicio no está activo, verificar si hay ticks recientes
        # (últimos 5 minutos) como indicador de que podría estar funcionando
        hace_5_minutos = timezone.now() - timedelta(minutes=5)
        ticks_recientes = Tick.objects.filter(epoch__gte=hace_5_minutos).exists()
        
        return ticks_recientes
    
    @staticmethod
    def obtener_resumen_estado() -> Dict[str, any]:
        """
        Obtiene un resumen del estado de todos los servicios.
        
        Returns:
            Dict con:
            - servicios: estado de cada servicio
            - todos_activos: bool - Si todos los servicios críticos están activos
            - servicios_criticos_activos: bool - Si los servicios críticos están activos
            - alertas: lista de alertas si hay servicios inactivos
        """
        estados = EstadoServiciosService.verificar_todos_servicios()
        
        # Servicios críticos (bot principal y recolector de ticks)
        servicios_criticos = ["bot_principal", "recolector_ticks"]
        
        todos_activos = all(
            estado.get("activo", False) 
            for estado in estados.values()
        )
        
        servicios_criticos_activos = all(
            estados[servicio].get("activo", False)
            for servicio in servicios_criticos
            if servicio in estados
        )
        
        # Generar alertas
        alertas = []
        for clave, estado in estados.items():
            if not estado.get("activo", False):
                nombre_servicio = EstadoServiciosService.SERVICIOS.get(clave, clave)
                alertas.append({
                    "servicio": clave,
                    "nombre": nombre_servicio,
                    "mensaje": f"El servicio {nombre_servicio} no está activo",
                    "estado": estado.get("estado", "unknown"),
                })
        
        return {
            "servicios": estados,
            "todos_activos": todos_activos,
            "servicios_criticos_activos": servicios_criticos_activos,
            "alertas": alertas,
            "timestamp": datetime.now().isoformat(),
        }

