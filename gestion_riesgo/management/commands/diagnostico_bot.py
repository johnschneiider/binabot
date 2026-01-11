from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.conf import settings

from gestion_riesgo.models import Cuenta, OperacionDeriv


class Command(BaseCommand):
    help = "Diagnóstico completo del estado del bot: bloqueos, señales, umbrales y razones por las que no opera."

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        tz = ZoneInfo("America/Bogota")
        ahora_epoch = int(time.time())
        ahora_dt = datetime.fromtimestamp(ahora_epoch, tz=tz)
        
        cuenta = Cuenta.objects.first()
        if not cuenta:
            self.stdout.write("❌ No hay cuenta configurada en la base de datos.")
            return
        
        self.stdout.write("=" * 80)
        self.stdout.write("DIAGNÓSTICO DEL BOT")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Hora actual (local): {ahora_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        self.stdout.write(f"Hora actual (UTC): {ahora_epoch}")
        self.stdout.write("")
        
        # ===== ESTADO DE BLOQUEO =====
        self.stdout.write("─" * 80)
        self.stdout.write("1. ESTADO DE BLOQUEO")
        self.stdout.write("─" * 80)
        bloqueado = getattr(cuenta, "bloqueado", False)
        riesgo_motivo = getattr(cuenta, "riesgo_motivo", "") or "N/A"
        
        if bloqueado:
            self.stdout.write(f"🔴 BLOQUEADO: Sí")
            self.stdout.write(f"   Motivo: {riesgo_motivo}")
        else:
            self.stdout.write(f"🟢 BLOQUEADO: No")
            if riesgo_motivo and riesgo_motivo != "N/A":
                self.stdout.write(f"   Estado: {riesgo_motivo}")
        
        # Verificar bloqueo por ciclo
        ciclo_pausa_hasta = getattr(cuenta, "ciclo_pausa_hasta_epoch", None)
        if ciclo_pausa_hasta:
            resta_seg = ciclo_pausa_hasta - ahora_epoch
            if resta_seg > 0:
                resta_min = resta_seg / 60
                self.stdout.write(f"   ⚠️  Pausa de ciclo activa: {resta_min:.1f} minutos restantes")
                self.stdout.write(f"      (hasta epoch {ciclo_pausa_hasta})")
            else:
                self.stdout.write(f"   ✅ Pausa de ciclo expirada (debería estar desbloqueado)")
        else:
            self.stdout.write(f"   ✅ Sin pausa de ciclo activa")
        
        self.stdout.write("")
        
        # ===== CONFIGURACIÓN DE UMBRALES =====
        self.stdout.write("─" * 80)
        self.stdout.write("2. CONFIGURACIÓN DE UMBRALES")
        self.stdout.write("─" * 80)
        umbral_compra = float(getattr(settings, "UMBRAL_COMPRA", 0.75))
        umbral_venta = float(getattr(settings, "UMBRAL_VENTA", -0.75))
        adaptativo_habilitado = bool(getattr(settings, "ADAPTATIVO_HABILITADO", False))
        
        self.stdout.write(f"Umbral COMPRA: {umbral_compra:.4f}")
        self.stdout.write(f"Umbral VENTA: {umbral_venta:.4f}")
        self.stdout.write(f"Adaptativo habilitado: {adaptativo_habilitado}")
        
        if adaptativo_habilitado:
            adapt_warmup = float(getattr(settings, "ADAPTATIVO_UMBRAL_WARMUP", 0.09))
            self.stdout.write(f"  ⚠️  Adaptativo activo - umbral warmup: {adapt_warmup:.4f}")
        else:
            self.stdout.write(f"  ✅ Usando umbrales fijos")
        
        self.stdout.write("")
        
        # ===== ÚLTIMA SEÑAL RECIBIDA =====
        self.stdout.write("─" * 80)
        self.stdout.write("3. ÚLTIMA SEÑAL RECIBIDA")
        self.stdout.write("─" * 80)
        senal_valor = getattr(cuenta, "senal_valor", None)
        senal_decision = getattr(cuenta, "senal_decision", "") or "N/A"
        
        if senal_valor is not None:
            self.stdout.write(f"Señal valor: {senal_valor:.6f}")
            self.stdout.write(f"Decisión: {senal_decision}")
            
            # Verificar si cumple umbral
            cumple_compra = senal_valor >= umbral_compra
            cumple_venta = senal_valor <= umbral_venta
            
            if cumple_compra:
                self.stdout.write(f"  ✅ CUMPLE UMBRAL COMPRA (señal {senal_valor:.6f} >= {umbral_compra:.4f})")
            elif cumple_venta:
                self.stdout.write(f"  ✅ CUMPLE UMBRAL VENTA (señal {senal_valor:.6f} <= {umbral_venta:.4f})")
            else:
                self.stdout.write(f"  ⚠️  NO CUMPLE NINGÚN UMBRAL")
                self.stdout.write(f"     (señal {senal_valor:.6f} está entre {umbral_venta:.4f} y {umbral_compra:.4f})")
        else:
            self.stdout.write("⚠️  No hay señal registrada aún")
        
        self.stdout.write("")
        
        # ===== ÚLTIMO TICK RECIBIDO =====
        self.stdout.write("─" * 80)
        self.stdout.write("4. ÚLTIMO TICK RECIBIDO")
        self.stdout.write("─" * 80)
        ultimo_tick_epoch = getattr(cuenta, "ultimo_tick_epoch", 0)
        ultimo_precio = getattr(cuenta, "ultimo_precio", 0.0)
        
        if ultimo_tick_epoch > 0:
            tick_dt = datetime.fromtimestamp(ultimo_tick_epoch, tz=tz)
            seg_desde_tick = ahora_epoch - ultimo_tick_epoch
            
            self.stdout.write(f"Último tick: {tick_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            self.stdout.write(f"Precio: {ultimo_precio:.6f}")
            self.stdout.write(f"Segundos desde último tick: {seg_desde_tick}")
            
            if seg_desde_tick > 300:  # 5 minutos
                self.stdout.write(f"  ⚠️  ADVERTENCIA: No hay ticks desde hace {seg_desde_tick/60:.1f} minutos")
            elif seg_desde_tick > 60:
                self.stdout.write(f"  ⚠️  Último tick hace {seg_desde_tick:.0f} segundos")
            else:
                self.stdout.write(f"  ✅ Ticks llegando normalmente")
        else:
            self.stdout.write("⚠️  No hay ticks registrados")
        
        self.stdout.write("")
        
        # ===== BLOQUEO POR HORARIO =====
        self.stdout.write("─" * 80)
        self.stdout.write("5. BLOQUEO POR HORARIO")
        self.stdout.write("─" * 80)
        hora_actual = ahora_dt.hour
        bloqueo_horas = getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""
        
        self.stdout.write(f"Hora actual (local): {hora_actual:02d}:00")
        self.stdout.write(f"Horas bloqueadas configuradas: {bloqueo_horas or 'Ninguna'}")
        
        # Parsear horas bloqueadas (simple)
        horas_bloqueadas_set = set()
        if bloqueo_horas:
            for part in bloqueo_horas.replace(" ", "").split(","):
                if "-" in part:
                    a, b = part.split("-", 1)
                    try:
                        for h in range(int(a), int(b) + 1):
                            if 0 <= h <= 23:
                                horas_bloqueadas_set.add(h)
                    except ValueError:
                        pass
                else:
                    try:
                        h = int(part)
                        if 0 <= h <= 23:
                            horas_bloqueadas_set.add(h)
                    except ValueError:
                        pass
        
        if hora_actual in horas_bloqueadas_set:
            self.stdout.write(f"  🔴 HORA ACTUAL ESTÁ BLOQUEADA")
        else:
            self.stdout.write(f"  ✅ Hora actual permitida para operar")
        
        if horas_bloqueadas_set:
            self.stdout.write(f"   Horas bloqueadas: {sorted(horas_bloqueadas_set)}")
        
        self.stdout.write("")
        
        # ===== TIPOS DE CONTRATO PERMITIDOS =====
        self.stdout.write("─" * 80)
        self.stdout.write("6. TIPOS DE CONTRATO")
        self.stdout.write("─" * 80)
        contract_types = getattr(settings, "DERIV_CONTRACT_TYPES_PERMITIDOS", ["PUT", "CALL"])
        self.stdout.write(f"Tipos permitidos: {', '.join(contract_types)}")
        self.stdout.write("")
        
        # ===== ÚLTIMA OPERACIÓN =====
        self.stdout.write("─" * 80)
        self.stdout.write("7. ÚLTIMA OPERACIÓN")
        self.stdout.write("─" * 80)
        ultima_op = OperacionDeriv.objects.filter(
            cuenta=cuenta,
            creada_por_bot=True
        ).order_by("-created_at").first()
        
        if ultima_op:
            op_dt = ultima_op.created_at.astimezone(tz)
            seg_desde_op = (ahora_epoch - int(ultima_op.opened_epoch)) if ultima_op.opened_epoch else None
            
            self.stdout.write(f"ID: {ultima_op.id}")
            self.stdout.write(f"Fecha: {op_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            self.stdout.write(f"Tipo: {ultima_op.contract_type}")
            self.stdout.write(f"Estado: {ultima_op.estado}")
            if ultima_op.profit is not None:
                self.stdout.write(f"Profit: {ultima_op.profit:.2f} USD")
            if hasattr(ultima_op, "umbral_usado") and ultima_op.umbral_usado:
                self.stdout.write(f"Umbral usado: {ultima_op.umbral_usado:.4f}")
            if seg_desde_op:
                self.stdout.write(f"Segundos desde apertura: {seg_desde_op}")
        else:
            self.stdout.write("⚠️  No hay operaciones registradas")
        
        # Verificar si hay operación abierta
        op_abierta = OperacionDeriv.objects.filter(
            cuenta=cuenta,
            creada_por_bot=True,
            estado="ABIERTA"
        ).first()
        
        if op_abierta:
            self.stdout.write(f"")
            self.stdout.write(f"  ⚠️  HAY OPERACIÓN ABIERTA (ID: {op_abierta.id})")
            self.stdout.write(f"     El bot no operará hasta que se cierre")
        else:
            self.stdout.write(f"  ✅ No hay operaciones abiertas")
        
        self.stdout.write("")
        
        # ===== RESUMEN Y RECOMENDACIÓN =====
        self.stdout.write("=" * 80)
        self.stdout.write("RESUMEN")
        self.stdout.write("=" * 80)
        
        razones_no_operar = []
        
        if bloqueado:
            razones_no_operar.append(f"Bot bloqueado: {riesgo_motivo}")
        
        if ciclo_pausa_hasta and ciclo_pausa_hasta > ahora_epoch:
            razones_no_operar.append(f"Pausa de ciclo activa ({int((ciclo_pausa_hasta - ahora_epoch)/60)} min restantes)")
        
        if hora_actual in horas_bloqueadas_set:
            razones_no_operar.append(f"Hora actual ({hora_actual:02d}:00) está bloqueada")
        
        if op_abierta:
            razones_no_operar.append(f"Hay operación abierta (ID: {op_abierta.id})")
        
        if senal_valor is not None:
            if not (senal_valor >= umbral_compra or senal_valor <= umbral_venta):
                razones_no_operar.append(f"Señal no cumple umbral (señal={senal_valor:.6f}, necesita >= {umbral_compra:.4f} o <= {umbral_venta:.4f})")
        
        if ultimo_tick_epoch == 0 or (ahora_epoch - ultimo_tick_epoch) > 300:
            razones_no_operar.append(f"No hay ticks recientes (último hace {ahora_epoch - ultimo_tick_epoch if ultimo_tick_epoch > 0 else 'N/A'} seg)")
        
        if razones_no_operar:
            self.stdout.write("🔴 RAZONES POR LAS QUE NO ESTÁ OPERANDO:")
            for i, razon in enumerate(razones_no_operar, 1):
                self.stdout.write(f"   {i}. {razon}")
        else:
            self.stdout.write("🟢 NO HAY BLOQUEOS DETECTADOS")
            if senal_valor is not None:
                if senal_valor >= umbral_compra:
                    self.stdout.write(f"   ✅ Señal cumple umbral COMPRA ({senal_valor:.6f} >= {umbral_compra:.4f})")
                elif senal_valor <= umbral_venta:
                    self.stdout.write(f"   ✅ Señal cumple umbral VENTA ({senal_valor:.6f} <= {umbral_venta:.4f})")
                else:
                    self.stdout.write(f"   ⚠️  Señal no cumple umbral (esperando señal >= {umbral_compra:.4f} o <= {umbral_venta:.4f})")
            else:
                self.stdout.write(f"   ⚠️  No hay señal registrada aún (esperando ticks)")
        
        self.stdout.write("")
