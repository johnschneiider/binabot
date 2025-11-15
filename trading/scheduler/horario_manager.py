"""
Gestión de optimización por horario y franjas rentables.
"""
from datetime import time, timedelta
from decimal import Decimal
from typing import Optional

from django.db.models import Avg, Count, Q
from django.utils import timezone

from core.models import ActivoPermitido
from historial.models import Operacion
from trading.models import RendimientoActivo


def obtener_confianza_horaria(
    activo: ActivoPermitido,
    hora_actual: Optional[time] = None,
    dias_analisis: int = 30,
) -> Decimal:
    """
    Obtiene la confianza horaria para un activo en una hora específica.
    
    Args:
        activo: Activo a analizar
        hora_actual: Hora actual (si None, usa la hora actual del sistema)
        dias_analisis: Días hacia atrás para el análisis
    
    Returns:
        Confianza horaria (0-100)
    """
    if hora_actual is None:
        hora_actual = timezone.localtime(timezone.now()).time()
    
    # Buscar rendimiento para esta hora
    try:
        rendimiento = RendimientoActivo.objects.get(
            activo=activo,
            hora=hora_actual,
        )
        return rendimiento.winrate_dinamico
    except RendimientoActivo.DoesNotExist:
        # Si no hay datos, calcular desde operaciones históricas
        return calcular_winrate_horario_desde_operaciones(
            activo, hora_actual, dias_analisis
        )


def calcular_winrate_horario_desde_operaciones(
    activo: ActivoPermitido,
    hora: time,
    dias: int = 30,
) -> Decimal:
    """
    Calcula el winrate para una hora específica desde operaciones históricas.
    
    Args:
        activo: Activo a analizar
        hora: Hora a analizar
        dias: Días hacia atrás
    
    Returns:
        Winrate (0-100)
    """
    desde = timezone.now() - timedelta(days=dias)
    
    # Obtener operaciones en esta hora
    operaciones = Operacion.objetos.reales().filter(
        activo=activo.nombre,
        hora_inicio__gte=desde,
    )
    
    # Filtrar por hora (considerando un rango de ±30 minutos)
    hora_min = (hora.hour * 60 + hora.minute - 30) % (24 * 60)
    hora_max = (hora.hour * 60 + hora.minute + 30) % (24 * 60)
    
    operaciones_hora = []
    for op in operaciones:
        if op.hora_inicio:
            op_hora = timezone.localtime(op.hora_inicio).time()
            op_minutos = op_hora.hour * 60 + op_hora.minute
            
            if hora_min <= hora_max:
                if hora_min <= op_minutos <= hora_max:
                    operaciones_hora.append(op)
            else:  # Cruza medianoche
                if op_minutos >= hora_min or op_minutos <= hora_max:
                    operaciones_hora.append(op)
    
    if not operaciones_hora:
        return Decimal("50.00")  # Valor neutro
    
    ganadas = sum(1 for op in operaciones_hora if op.resultado == Operacion.Resultado.GANADA)
    total = len(operaciones_hora)
    
    winrate = (Decimal(str(ganadas)) / Decimal(str(total)) * Decimal("100")).quantize(
        Decimal("0.01")
    )
    
    return winrate


@transaction.atomic
def actualizar_rendimiento_horario(
    activo: ActivoPermitido,
    operacion: Operacion,
) -> None:
    """
    Actualiza el rendimiento horario después de una operación.
    
    Args:
        activo: Activo operado
        operacion: Operación completada
    """
    if not operacion.hora_inicio:
        return
    
    hora_op = timezone.localtime(operacion.hora_inicio).time()
    hora_redondeada = time(hour=hora_op.hour, minute=(hora_op.minute // 30) * 30)
    
    rendimiento, creado = RendimientoActivo.objects.get_or_create(
        activo=activo,
        hora=hora_redondeada,
        defaults={
            "winrate_dinamico": Decimal("0.00"),
            "total_operaciones": 0,
            "operaciones_ganadas": 0,
            "operaciones_perdidas": 0,
            "beneficio_total": Decimal("0.00"),
            "perdida_total": Decimal("0.00"),
        },
    )
    
    # Actualizar estadísticas
    rendimiento.total_operaciones += 1
    
    if operacion.resultado == Operacion.Resultado.GANADA:
        rendimiento.operaciones_ganadas += 1
        rendimiento.beneficio_total += operacion.beneficio
    elif operacion.resultado == Operacion.Resultado.PERDIDA:
        rendimiento.operaciones_perdidas += 1
        rendimiento.perdida_total += abs(operacion.beneficio)
    
    # Recalcular winrate dinámico (últimas 50 operaciones)
    desde = timezone.now() - timedelta(days=30)
    operaciones_recientes = Operacion.objetos.reales().filter(
        activo=activo.nombre,
        hora_inicio__gte=desde,
    ).order_by("-hora_inicio")[:50]
    
    if operaciones_recientes:
        ganadas_recientes = sum(
            1 for op in operaciones_recientes
            if op.resultado == Operacion.Resultado.GANADA
        )
        rendimiento.winrate_dinamico = (
            Decimal(str(ganadas_recientes))
            / Decimal(str(len(operaciones_recientes)))
            * Decimal("100")
        ).quantize(Decimal("0.01"))
    
    rendimiento.save()


def obtener_mejor_horario_activo(
    activo: ActivoPermitido,
    umbral_minimo: Decimal = Decimal("55.00"),
) -> Optional[time]:
    """
    Obtiene el mejor horario para operar un activo.
    
    Args:
        activo: Activo a analizar
        umbral_minimo: Winrate mínimo para considerar un horario
    
    Returns:
        Mejor horario o None si no hay horarios rentables
    """
    rendimientos = RendimientoActivo.objects.filter(
        activo=activo,
        winrate_dinamico__gte=umbral_minimo,
        total_operaciones__gte=5,  # Mínimo 5 operaciones para considerar
    ).order_by("-winrate_dinamico")
    
    if rendimientos.exists():
        return rendimientos.first().hora
    
    return None

