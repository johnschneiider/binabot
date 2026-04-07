"""
AUDITORÍA DE SEGURIDAD - Binary Bot
Verifica posibles indicadores de compromiso
"""
import os
import sqlite3
from datetime import datetime, timedelta
import subprocess

def ejecutar_comando(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout, result.returncode
    except Exception as e:
        return str(e), 1

def audit_binancial():
    """Verifica operaciones financieras recientes"""
    print("\n=== BALANCE ACTUAL ===")
    try:
        import os, time, hmac, hashlib, requests
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if api_key and api_secret:
            timestamp = int(time.time() * 1000)
            query = f'timestamp={timestamp}'
            sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            
            url = f'https://fapi.binance.com/fapi/v2/account?{query}&signature={sig}'
            headers = {'X-MBX-APIKEY': api_key}
            
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                print(f"Balance Wallet: {data.get('totalWalletBalance', 'N/A')} USDT")
                print(f"Balance Disponible: {data.get('availableBalance', 'N/A')} USDT")
                print(f"Positions Abiertas: {data.get('totalOpenPosition', 0)}")
    except Exception as e:
        print(f"Error consultando Binance: {e}")

def audit_sesiones():
    """Verifica sesiones activas"""
    print("\n=== SESIONES ACTIVAS ===")
    output, _ = ejecutar_comando('tasklist | findstr python')
    count = output.count('\n')
    print(f"Procesos Python activos: {count}")
    print(output[:1000] if output else "Ninguno")

def audit_conexiones():
    """Verifica conexiones de red sospechosas"""
    print("\n=== CONEXIONES DE RED ===")
    output, _ = ejecutar_comando('netstat -ano | findstr ESTABLISHED')
    print(f"Conexiones establecidas: {output.count('ESTABLISHED')}")
    # Buscar IPs Extrañas
    for line in output.split('\n'):
        if 'TIME_WAIT' not in line and line.strip():
            print(f"  {line[:100]}")

def audit_ultimas_operaciones():
    """Verifica últimas operaciones en BD"""
    print("\n=== ÚLTIMAS OPERACIONES (BD) ===")
    try:
        conn = sqlite3.connect('db.sqlite3')
        cur = conn.cursor()
        cur.execute("SELECT id, simbolo, direccion, es_win, profit, created_at FROM gestion_riesgo_operacionbinance ORDER BY id DESC LIMIT 10")
        rows = cur.fetchall()
        if rows:
            for r in rows:
                print(f"  {r}")
        else:
            print("  Sin operaciones registradas")
        conn.close()
    except Exception as e:
        print(f"  Error BD: {e}")

def audit_logs():
    """Busca patrones sospechosos en logs"""
    print("\n=== PATRONES SOSPECHOSOS EN LOGS ===")
    patrones = ['ERROR', 'UNAUTHORIZED', 'signature', 'password', 'hack', 'inject']
    archivos = ['binance_bot.log', 'django.log', 'server.log']
    
    for archivo in archivos:
        try:
            with open(archivo, 'r', encoding='utf-8', errors='ignore') as f:
                lineas = f.readlines()[-1000:]
                for patron in patrones:
                    matches = [l for l in lineas if patron.lower() in l.lower()]
                    if matches:
                        print(f"  {archivo}: {patron} encontrado {len(matches)} veces")
        except:
            pass

def audit_django_users():
    """Verifica usuarios de Django"""
    print("\n=== USUARIOS DJANGO ===")
    try:
        import os, django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
        django.setup()
        from django.contrib.auth.models import User
        for u in User.objects.all()[:10]:
            print(f"  {u.username} | superuser:{u.is_superuser} | staff:{u.is_staff}")
    except Exception as e:
        print(f"  Error: {e}")

def audit_env():
    """Verifica variables de entorno sensibles"""
    print("\n=== VARIABLES DE ENTORNO ===")
    sensitive = ['BINANCE', 'DERIV', 'SECRET', 'PASSWORD', 'TOKEN', 'KEY']
    for key in sorted(os.environ.keys()):
        for s in sensitive:
            if s in key.upper():
                val = os.environ[key]
                if len(val) > 5:
                    print(f"  {key}: {val[:4]}***{val[-4:]}")

if __name__ == '__main__':
    print("=" * 50)
    print("AUDITORÍA DE SEGURIDAD - BINARY BOT")
    print("=" * 50)
    print(f"Ejecutado: {datetime.now()}")
    
    audit_binancial()
    audit_sesiones()
    audit_conexiones()
    audit_ultimas_operaciones()
    audit_logs()
    audit_django_users()
    audit_env()
    
    print("\n" + "=" * 50)
    print("AUDITORÍA COMPLETA")
    print("=" * 50)
