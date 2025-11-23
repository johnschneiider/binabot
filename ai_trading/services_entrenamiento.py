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
        global _proceso_entrenamiento_actual, _hilo_entrenamiento_actual, _entrenamiento_actual
        
        try:
            # Obtener la ruta del manage.py - buscar desde el directorio actual
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            manage_py = os.path.join(base_dir, 'manage.py')
            
            # Si no existe, intentar desde el directorio del proyecto
            if not os.path.exists(manage_py):
                # Buscar en el directorio padre
                base_dir = os.path.dirname(base_dir)
                manage_py = os.path.join(base_dir, 'manage.py')
            
            # Verificar que existe
            if not os.path.exists(manage_py):
                error_msg = f"No se encontró manage.py. Buscado en: {manage_py}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
            
            logger.info(f"Usando manage.py en: {manage_py}")
            
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
            logger.info(f"Directorio de trabajo: {os.getcwd()}")
            logger.info(f"Python ejecutable: {sys.executable}")
            
            # Ejecutar comando con mejor manejo de errores
            proceso = subprocess.Popen(
                comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                cwd=base_dir,  # Ejecutar desde el directorio del proyecto
            )
            
            _proceso_entrenamiento_actual = proceso
            
            # Leer salida línea por línea desde stdout
            salida_completa = []
            for linea in proceso.stdout:
                linea_limpia = linea.strip()
                if linea_limpia:
                    logger.info(f"[Entrenamiento] {linea_limpia}")
                    salida_completa.append(linea_limpia)
            
            # Leer errores de stderr
            errores = []
            for linea in proceso.stderr:
                linea_limpia = linea.strip()
                if linea_limpia:
                    logger.error(f"[Entrenamiento ERROR] {linea_limpia}")
                    errores.append(linea_limpia)
            
            # Esperar a que termine
            returncode = proceso.wait()
            
            logger.info(f"Proceso terminado con código: {returncode}")
            
            # Actualizar estado
            with transaction.atomic():
                entrenamiento.refresh_from_db()
                if returncode == 0:
                    entrenamiento.estado = EntrenamientoIA.Estado.COMPLETADO
                    mensaje = f"Entrenamiento '{nombre_entrenamiento}' completado exitosamente"
                    logger.info(mensaje)
                    enviar_estado_entrenamiento(
                        "completado",
                        mensaje,
                        entrenamiento.id
                    )
                else:
                    error_detalle = '\n'.join(errores[-10:]) if errores else 'Sin detalles de error'
                    mensaje = f"Entrenamiento '{nombre_entrenamiento}' terminó con error (código {returncode})"
                    logger.error(f"{mensaje}\nErrores: {error_detalle}")
                    entrenamiento.estado = EntrenamientoIA.Estado.ERROR
                    enviar_estado_entrenamiento(
                        "error",
                        f"{mensaje}. Últimos errores: {error_detalle[:200]}",
                        entrenamiento.id
                    )
                entrenamiento.finalizada = timezone.now()
                entrenamiento.save()
            
        except FileNotFoundError as e:
            error_msg = f"Error: No se encontró manage.py o Python. {str(e)}"
            logger.error(error_msg, exc_info=True)
            with transaction.atomic():
                entrenamiento.refresh_from_db()
                entrenamiento.estado = EntrenamientoIA.Estado.ERROR
                entrenamiento.finalizada = timezone.now()
                entrenamiento.save()
                enviar_estado_entrenamiento(
                    "error",
                    error_msg,
                    entrenamiento.id
                )
        except Exception as e:
            error_msg = f"Error durante el entrenamiento: {str(e)}"
            logger.error(error_msg, exc_info=True)
            with transaction.atomic():
                entrenamiento.refresh_from_db()
                entrenamiento.estado = EntrenamientoIA.Estado.ERROR
                entrenamiento.finalizada = timezone.now()
                entrenamiento.save()
                enviar_estado_entrenamiento(
                    "error",
                    error_msg,
                    entrenamiento.id
                )
        finally:
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

