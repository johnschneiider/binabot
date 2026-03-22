"""
Script de monitoreo en tiempo real del bot
Ejecuta el bot y monitorea el balance hasta alcanzar el target
"""

import os
import sys
import time
import subprocess
import threading
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
import django
django.setup()

from gestion_riesgo.models import Cuenta, OperacionDeriv

class MonitorBot:
    def __init__(self):
        self.balance_inicial = None
        self.target = None
        self.parar = False
        self.bot_process = None
        
    def obtener_balance(self):
        """Obtiene el balance actual de R_100"""
        try:
            cuenta = Cuenta.objects.filter(simbolo='R_100').first()
            if cuenta and cuenta.balance_deriv:
                return float(cuenta.balance_deriv)
        except:
            pass
        return None
    
    def obtener_estadisticas(self):
        """Obtiene estadísticas de trading"""
        try:
            cuenta = Cuenta.objects.filter(simbolo='R_100').first()
            if not cuenta:
                return None
            
            ops = OperacionDeriv.objects.filter(
                cuenta=cuenta, 
                creada_por_bot=True, 
                estado='CERRADA'
            )
            total = ops.count()
            wins = ops.filter(profit__gt=0).count()
            winrate = (wins / total * 100) if total > 0 else 0
            
            # Últimas 15 operaciones
            ultimas = ops.order_by('-closed_epoch')[:15]
            ultimas_wins = sum(1 for op in ultimas if op.profit and op.profit > 0)
            ultimas_total = ultimas.count()
            ultimas_winrate = (ultimas_wins / ultimas_total * 100) if ultimas_total > 0 else 0
            
            return {
                'total_ops': total,
                'wins': wins,
                'losses': total - wins,
                'winrate': winrate,
                'ultimas_winrate': ultimas_winrate,
                'ultimas_total': ultimas_total
            }
        except:
            return None
    
    def mostrar_progreso(self, balance):
        """Muestra el progreso actual"""
        if self.balance_inicial is None:
            self.balance_inicial = balance
            self.target = balance * 1.10
        
        profit = balance - self.balance_inicial
        profit_pct = (profit / self.balance_inicial * 100) if self.balance_inicial > 0 else 0
        restante = self.target - balance
        restante_pct = (restante / balance * 100) if balance > 0 else 0
        
        stats = self.obtener_estadisticas()
        
        os.system('cls' if os.name == 'nt' else 'clear')
        
        print("=" * 60)
        print("        MONITOR DE BOT - TRADING EN TIEMPO REAL")
        print("=" * 60)
        print(f"  Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        print()
        print(f"  BALANCE ACTUAL:      ${balance:.2f}")
        print(f"  BALANCE INICIAL:     ${self.balance_inicial:.2f}")
        print(f"  TARGET (10%):        ${self.target:.2f}")
        print()
        print(f"  PROFIT:              ${profit:.2f} ({profit_pct:.2f}%)")
        print(f"  RESTANTE:            ${restante:.2f} ({restante_pct:.2f}%)")
        print()
        
        # Barra de progreso
        progreso = min(100, max(0, profit_pct * 10))  # 10% = 100%
        barra_len = 40
        barra_llenada = int(barra_len * progreso / 100)
        barra = "█" * barra_llenada + "░" * (barra_len - barra_llenada)
        print(f"  PROGRESO: [{barra}] {progreso:.1f}%")
        print()
        
        if stats:
            print(f"  ESTADÍSTICAS DE TRADING:")
            print(f"    Total operaciones: {stats['total_ops']}")
            print(f"    Wins: {stats['wins']} | Losses: {stats['losses']}")
            print(f"    Winrate total: {stats['winrate']:.1f}%")
            print(f"    Winrate últimas 15: {stats['ultimas_winrate']:.1f}%")
        print()
        print("=" * 60)
        print("  Ctrl+C para detener manualmente")
        print("=" * 60)
        
        return profit_pct >= 10
    
    def iniciar_bot(self):
        """Inicia el bot en un proceso separado"""
        cmd = [
            sys.executable, 'manage.py', 'bot_con_panel',
            '--symbols', 'R_100',
            '--real',
            '--ilimitado',
            '--permitir-sin-venv'
        ]
        
        self.bot_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Leer output en thread separado
        def leer_output():
            for line in self.bot_process.stdout:
                if 'TRADING' in line or 'profit' in line.lower():
                    print(f"  [BOT] {line.strip()}")
        
        thread = threading.Thread(target=leer_output, daemon=True)
        thread.start()
        
        return self.bot_process
    
    def ejecutar(self):
        """Ejecuta el monitoreo"""
        print("Iniciando bot...")
        self.iniciar_bot()
        
        # Esperar a que el bot se inicie
        time.sleep(10)
        
        print("Bot iniciado. Monitoreando balance...")
        time.sleep(5)
        
        intentos = 0
        while not self.parar and intentos < 300:  # Max 30 minutos
            try:
                balance = self.obtener_balance()
                
                if balance and balance > 0:
                    objetivo_alcanzado = self.mostrar_progreso(balance)
                    
                    if objetivo_alcanzado:
                        print()
                        print("🎉 ¡OBJETIVO ALCANZADO! 🎉")
                        print(f"Se ganó el 10% del balance!")
                        self.parar = True
                        break
                
                time.sleep(3)  # Verificar cada 3 segundos
                intentos += 1
                
            except KeyboardInterrupt:
                print("\n\nDetenido por el usuario.")
                self.parar = True
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(5)
        
        # Detener bot
        if self.bot_process:
            self.bot_process.terminate()
            print("Bot detenido.")
        
        print("\nResumen final:")
        balance_final = self.obtener_balance()
        if balance_final and self.balance_inicial:
            profit = balance_final - self.balance_inicial
            print(f"  Balance inicial: ${self.balance_inicial:.2f}")
            print(f"  Balance final: ${balance_final:.2f}")
            print(f"  Profit: ${profit:.2f} ({(profit/self.balance_inicial*100):.2f}%)")

if __name__ == "__main__":
    monitor = MonitorBot()
    try:
        monitor.ejecutar()
    except KeyboardInterrupt:
        print("\nDetenido por usuario.")
        if monitor.bot_process:
            monitor.bot_process.terminate()
