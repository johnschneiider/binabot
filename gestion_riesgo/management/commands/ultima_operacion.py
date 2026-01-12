from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from gestion_riesgo.models import OperacionDeriv


class Command(BaseCommand):
    help = "Muestra la última operación con detalles completos, incluyendo hora local y verificación de bloqueo horario."

    def add_arguments(self, parser):
        parser.add_argument("--n", type=int, default=1, help="Número de últimas operaciones a mostrar (default: 1)")
        parser.add_argument("--verificar-horario", action="store_true", help="Verifica si operó en horas bloqueadas")

    def handle(self, *args, **opts):
        n = int(opts.get("n", 1))
        verificar_horario = bool(opts.get("verificar_horario", False))
        
        tz = ZoneInfo("America/Bogota")
        
        # Obtener últimas operaciones
        ops = (
            OperacionDeriv.objects.filter(creada_por_bot=True)
            .order_by("-opened_epoch")
            [:n]
        )
        
        if not ops.exists():
            self.stdout.write("❌ No hay operaciones registradas")
            return
        
        self.stdout.write("=" * 80)
        self.stdout.write(f"ÚLTIMA{'S' if n > 1 else ''} OPERACIÓN{'ES' if n > 1 else ''} (BOT)")
        self.stdout.write("=" * 80)
        self.stdout.write("")
        
        for i, op in enumerate(ops, 1):
            if n > 1:
                self.stdout.write(f"--- Operación #{i} ---")
                self.stdout.write("")
            
            # Fechas en hora local
            opened_dt = datetime.fromtimestamp(int(op.opened_epoch), tz=tz) if op.opened_epoch else None
            closed_dt = datetime.fromtimestamp(int(op.closed_epoch), tz=tz) if op.closed_epoch else None
            
            self.stdout.write(f"ID: {op.id}")
            self.stdout.write(f"Símbolo: {op.simbolo or 'N/A'}")
            self.stdout.write(f"Tipo: {op.contract_type}")
            self.stdout.write(f"Estado: {op.estado}")
            self.stdout.write("")
            
            # Apertura
            if opened_dt:
                hora_apertura = opened_dt.hour
                self.stdout.write(f"Apertura:")
                self.stdout.write(f"  Fecha/hora (local): {opened_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                self.stdout.write(f"  Hora del día: {hora_apertura:02d}:00")
                self.stdout.write(f"  Epoch: {op.opened_epoch}")
            else:
                self.stdout.write("Apertura: N/A")
            
            self.stdout.write("")
            
            # Cierre
            if closed_dt:
                hora_cierre = closed_dt.hour
                self.stdout.write(f"Cierre:")
                self.stdout.write(f"  Fecha/hora (local): {closed_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                self.stdout.write(f"  Hora del día: {hora_cierre:02d}:00")
                self.stdout.write(f"  Epoch: {op.closed_epoch}")
            else:
                self.stdout.write("Cierre: Pendiente")
            
            self.stdout.write("")
            
            # Profit y umbral
            if op.profit is not None:
                self.stdout.write(f"Profit: {op.profit:.2f} {op.moneda}")
            else:
                self.stdout.write("Profit: Pendiente")
            
            if op.umbral_usado is not None:
                self.stdout.write(f"Umbral usado: {op.umbral_usado:.4f}")
            
            self.stdout.write("")
            
            # Verificación de horario bloqueado
            if verificar_horario and opened_dt:
                from django.conf import settings
                from vector_variables.management.commands.deriv_stream import Command as StreamCommand
                
                horas_bloqueadas_str = getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "")
                horas_bloqueadas = StreamCommand._parse_horas_bloqueadas(horas_bloqueadas_str)
                
                if horas_bloqueadas:
                    if hora_apertura in horas_bloqueadas:
                        self.stdout.write(f"⚠️  ADVERTENCIA: Operó en hora BLOQUEADA ({hora_apertura:02d}:00)")
                        self.stdout.write(f"   Horas bloqueadas configuradas: {sorted(horas_bloqueadas)}")
                    else:
                        self.stdout.write(f"✅ Operó en hora PERMITIDA ({hora_apertura:02d}:00)")
                        self.stdout.write(f"   Horas bloqueadas configuradas: {sorted(horas_bloqueadas)}")
                else:
                    self.stdout.write(f"ℹ️  No hay horas bloqueadas configuradas")
            
            if i < len(ops):
                self.stdout.write("")
        
        self.stdout.write("")
        self.stdout.write("=" * 80)
