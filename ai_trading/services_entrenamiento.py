"""
Servicio para gestionar el entrenamiento de IA de forma asíncrona.
"""
import threading
import subprocess
import sys
import os
from django.utils import timezone
from django.db import transaction
from ai_trading.models import EntrenamientoIA
from ai_trading.services_websocket import enviar_estado_entrenamiento
import logging

logger = logging.getLogger(__name__)

# Variable global para el proceso de entrenamiento actual
_proceso_entrenamiento_actual = None
_hilo_entrenamiento_actual = None
_entrenamiento_actual = None


def iniciar_entrenamiento(
    generaciones: int = 10,
    poblacion: int = 20,
    tasa_mutacion: float = 0.10,
    tasa_crossover: float = 0.80,
    elite_size: int = 5,
    dias_datos: int = 1,
    nombre: str = None,
) -> EntrenamientoIA:
    """
    Inicia un entrenamiento de IA en un hilo separado.
    
    Returns:
        EntrenamientoIA: El objeto de entrenamiento creado
    """
    global _proceso_entrenamiento_actual, _hilo_entrenamiento_actual, _entrenamiento_actual
    
    # Verificar si ya hay un entrenamiento en curso
    if _entrenamiento_actual and _entrenamiento_actual.estado == EntrenamientoIA.Estado.EN_CURSO:
        raise ValueError("Ya hay un entrenamiento en curso")
    
    # Crear registro de entrenamiento
    nombre_entrenamiento = nombre or f"Entrenamiento_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
    
    with transaction.atomic():
        entrenamiento = EntrenamientoIA.objects.create(
            nombre=nombre_entrenamiento,
            tipo="genetico",
            estado=EntrenamientoIA.Estado.EN_CURSO,
            iniciada=timezone.now(),
            parametros={
                "generaciones": generaciones,
                "poblacion": poblacion,
                "tasa_mutacion": tasa_mutacion,
                "tasa_crossover": tasa_crossover,
                "elite_size": elite_size,
                "dias_datos": dias_datos,
            }
        )
        _entrenamiento_actual = entrenamiento
    
    # Enviar notificación de inicio
    enviar_estado_entrenamiento(
        "iniciado",
        f"Entrenamiento '{nombre_entrenamiento}' iniciado",
        entrenamiento.id
    )
    
    # Ejecutar en hilo separado
    def ejecutar_entrenamiento():
        global _proceso_entrenamiento_actual, _entrenamiento_actual
        
        try:
            # Obtener la ruta del manage.py
            manage_py = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'manage.py')
            if not os.path.exists(manage_py):
                # Intentar ruta alternativa
                manage_py = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'manage.py')
            
            # Construir comando
            comando = [
                sys.executable,
                manage_py,
                'entrenar_ia',
                '--generaciones', str(generaciones),
                '--poblacion', str(poblacion),
                '--mutacion', str(tasa_mutacion),
                '--crossover', str(tasa_crossover),
                '--elite', str(elite_size),
                '--dias-datos', str(dias_datos),
                '--nombre', nombre_entrenamiento,
            ]
            
            logger.info(f"Iniciando entrenamiento: {' '.join(comando)}")
            
            # Ejecutar comando
            proceso = subprocess.Popen(
                comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            
            _proceso_entrenamiento_actual = proceso
            
            # Leer salida línea por línea
            for linea in proceso.stdout:
                logger.info(f"[Entrenamiento] {linea.strip()}")
            
            # Esperar a que termine
            proceso.wait()
            
            # Actualizar estado
            with transaction.atomic():
                entrenamiento.refresh_from_db()
                if proceso.returncode == 0:
                    entrenamiento.estado = EntrenamientoIA.Estado.COMPLETADO
                    enviar_estado_entrenamiento(
                        "completado",
                        f"Entrenamiento '{nombre_entrenamiento}' completado exitosamente",
                        entrenamiento.id
                    )
                else:
                    entrenamiento.estado = EntrenamientoIA.Estado.ERROR
                    enviar_estado_entrenamiento(
                        "error",
                        f"Entrenamiento '{nombre_entrenamiento}' terminó con error",
                        entrenamiento.id
                    )
                entrenamiento.finalizada = timezone.now()
                entrenamiento.save()
            
        except Exception as e:
            logger.error(f"Error durante el entrenamiento: {e}", exc_info=True)
            with transaction.atomic():
                entrenamiento.refresh_from_db()
                entrenamiento.estado = EntrenamientoIA.Estado.ERROR
                entrenamiento.finalizada = timezone.now()
                entrenamiento.save()
                enviar_estado_entrenamiento(
                    "error",
                    f"Error durante el entrenamiento: {str(e)}",
                    entrenamiento.id
                )
        finally:
            global _proceso_entrenamiento_actual, _hilo_entrenamiento_actual
            _proceso_entrenamiento_actual = None
            _hilo_entrenamiento_actual = None
    
    _hilo_entrenamiento_actual = threading.Thread(target=ejecutar_entrenamiento, daemon=True)
    _hilo_entrenamiento_actual.start()
    
    return entrenamiento


def detener_entrenamiento():
    """Detiene el entrenamiento actual si está en curso."""
    global _proceso_entrenamiento_actual, _hilo_entrenamiento_actual, _entrenamiento_actual
    
    if not _proceso_entrenamiento_actual:
        return False
    
    try:
        # Terminar proceso
        _proceso_entrenamiento_actual.terminate()
        _proceso_entrenamiento_actual.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # Forzar terminación
        _proceso_entrenamiento_actual.kill()
    except Exception as e:
        logger.error(f"Error al detener entrenamiento: {e}")
    
    # Actualizar estado
    if _entrenamiento_actual:
        with transaction.atomic():
            _entrenamiento_actual.refresh_from_db()
            _entrenamiento_actual.estado = EntrenamientoIA.Estado.DETENIDO
            _entrenamiento_actual.finalizada = timezone.now()
            _entrenamiento_actual.save()
            enviar_estado_entrenamiento(
                "detenido",
                "Entrenamiento detenido por el usuario",
                _entrenamiento_actual.id
            )
    
    _proceso_entrenamiento_actual = None
    _hilo_entrenamiento_actual = None
    
    return True


def obtener_estado_entrenamiento():
    """Obtiene el estado del entrenamiento actual."""
    global _entrenamiento_actual, _proceso_entrenamiento_actual
    
    if not _entrenamiento_actual:
        return None
    
    estado = {
        "entrenamiento_id": _entrenamiento_actual.id,
        "nombre": _entrenamiento_actual.nombre,
        "estado": _entrenamiento_actual.estado,
        "iniciada": _entrenamiento_actual.iniciada.isoformat() if _entrenamiento_actual.iniciada else None,
        "finalizada": _entrenamiento_actual.finalizada.isoformat() if _entrenamiento_actual.finalizada else None,
        "parametros": _entrenamiento_actual.parametros or {},
        "en_curso": _proceso_entrenamiento_actual is not None,
    }
    
    return estado

