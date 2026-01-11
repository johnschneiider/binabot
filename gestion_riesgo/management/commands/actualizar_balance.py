from __future__ import annotations

import asyncio
import time

from django.core.management.base import BaseCommand
from django.conf import settings

from gestion_riesgo.models import BalanceDerivSnapshot, Cuenta
from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS


class Command(BaseCommand):
    help = "Fuerza actualización del balance desde Deriv API (útil si el WebSocket no está actualizando)."

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        cuenta = Cuenta.objects.first()
        if not cuenta:
            self.stdout.write("❌ No hay cuenta configurada.")
            return

        token = getattr(settings, "DERIV_API_TOKEN", "")
        if not token:
            self.stdout.write("❌ DERIV_API_TOKEN no configurado. No se puede obtener balance.")
            return

        self.stdout.write("Conectando a Deriv API para obtener balance actual...")
        
        async def obtener_balance() -> tuple[float, str] | None:
            try:
                async with ClienteDerivWS(token=token) as cliente:
                    # Enviar request de balance
                    await cliente.enviar({"balance": 1})
                    
                    # Esperar respuesta
                    respuesta = await cliente.recibir(timeout_segundos=10)
                    
                    if respuesta.get("error"):
                        self.stderr.write(f"❌ Error de Deriv: {respuesta['error']}")
                        return None
                    
                    balance_info = respuesta.get("balance", {})
                    if not balance_info:
                        self.stderr.write("❌ No se recibió información de balance en la respuesta.")
                        return None
                    
                    balance_val = float(balance_info.get("balance", 0))
                    currency = str(balance_info.get("currency", "USD"))
                    
                    return (balance_val, currency)
            except Exception as e:
                self.stderr.write(f"❌ Error al obtener balance: {e}")
                return None

        resultado = asyncio.run(obtener_balance())
        
        if resultado is None:
            self.stdout.write("No se pudo obtener el balance.")
            return

        balance_val, currency = resultado
        
        self.stdout.write(f"✅ Balance obtenido: {balance_val:.2f} {currency}")
        
        # Obtener balance anterior
        balance_anterior = getattr(cuenta, "balance_deriv", None) or 0.0
        diferencia = balance_val - float(balance_anterior)
        
        self.stdout.write(f"   Balance anterior (BD): {balance_anterior:.2f}")
        self.stdout.write(f"   Diferencia: {diferencia:+.2f} {currency}")
        
        # Actualizar cuenta
        max_balance_actual = float(getattr(cuenta, "max_balance_deriv_historico", 0.0) or 0.0)
        nuevo_max = max(max_balance_actual, balance_val)
        
        cuenta.balance_deriv = balance_val
        cuenta.moneda_deriv = currency
        cuenta.max_balance_deriv_historico = nuevo_max
        cuenta.save()
        
        self.stdout.write(f"✅ Balance actualizado en BD")
        self.stdout.write(f"   Nuevo max histórico: {nuevo_max:.2f} {currency}")
        
        # Crear snapshot para la gráfica
        try:
            BalanceDerivSnapshot.objects.create(
                cuenta=cuenta,
                balance=balance_val,
                moneda=currency,
                epoch=int(time.time()),
            )
            self.stdout.write(f"✅ Snapshot creado para la gráfica")
        except Exception as e:
            self.stderr.write(f"⚠️  No se pudo crear snapshot: {e}")
        
        # Verificar operaciones recientes
        from gestion_riesgo.models import OperacionDeriv
        ops_recientes = OperacionDeriv.objects.filter(
            cuenta=cuenta,
            creada_por_bot=True
        ).order_by("-created_at")[:5]
        
        if ops_recientes:
            self.stdout.write(f"\n📊 Últimas 5 operaciones:")
            for op in ops_recientes:
                profit_str = f"{op.profit:.2f}" if op.profit is not None else "N/A"
                self.stdout.write(f"   ID {op.id}: {op.contract_type} | {op.estado} | Profit: {profit_str}")
