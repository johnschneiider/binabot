import os, django, json, statistics
from decimal import Decimal

# Django Setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()

from gestion_riesgo.models import TickBinance

def ema_calc(precio, prev, periodo):
    if prev is None: return precio
    a = 2.0 / (periodo + 1.0)
    return a * precio + (1.0 - a) * prev

def adx_calc(precios, n=14):
    if len(precios) < n + 2: return 0.0
    dm_up, dm_dn, tr_list = [], [], []
    for i in range(1, len(precios)):
        h = float(max(precios[i], precios[i-1]))
        l = float(min(precios[i], precios[i-1]))
        pc = float(precios[i-1])
        up = h - pc
        dn = pc - l
        dm_up.append(up if up > dn and up > 0 else 0)
        dm_dn.append(dn if dn > up and dn > 0 else 0)
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not tr_list: return 0.0
    atr = sum(tr_list[-n:]) / n or 1
    dip = sum(dm_up[-n:]) / n / atr * 100
    dim = sum(dm_dn[-n:]) / n / atr * 100
    if dip + dim == 0: return 0.0
    return abs(dip - dim) / (dip + dim) * 100

def analyze():
    with open("/var/www/intradia.com.co/bot_config.json", "r") as f:
        cfg = json.load(f)
    
    simbolos = ["BTC", "ETH", "SOL", "XRP"]
    print(f"{'='*60}")
    print(f"  ANALISIS DE TICKS (Últimos 200 por activo)")
    print(f"  Configuración: ADX > {cfg['ADX_MIN']} | Gap > {cfg['EMA_GAP_PCT']}% | Mom > {cfg['MOMENTUM_MIN_PCT']}%")
    print(f"{'='*60}\n")
    
    for sym in simbolos:
        ticks = list(TickBinance.objects.filter(simbolo=sym).order_by('id'))
        if len(ticks) < 100:
            print(f"  {sym}: No hay suficientes ticks ({len(ticks)})")
            continue
            
        precios = [float(t.precio) for t in ticks]
        
        # Simular indicadores
        e5, e21, e55 = None, None, None
        max_adx, max_gap, max_mom = 0.0, 0.0, 0.0
        meets_all = 0
        
        for i in range(len(precios)):
            p = precios[i]
            e5 = ema_calc(p, e5, 5)
            e21 = ema_calc(p, e21, 21)
            e55 = ema_calc(p, e55, 55)
            
            if i < 55: continue # Warmup
            
            adx_val = adx_calc(precios[:i+1])
            gap = abs(e5 - e55) / e55 * 100
            mom = 0.0
            if i >= 15:
                base = precios[i-15]
                mom = abs(p - base) / base * 100
                
            max_adx = max(max_adx, adx_val)
            max_gap = max(max_gap, gap)
            max_mom = max(max_mom, mom)
            
            if adx_val >= cfg['ADX_MIN'] and gap >= cfg['EMA_GAP_PCT'] and mom >= cfg['MOMENTUM_MIN_PCT']:
                meets_all += 1
                
        print(f"  [{sym}] Máximos detectados:")
        print(f"    - ADX: {max_adx:.1f} (Se requiere {cfg['ADX_MIN']})")
        print(f"    - Gap: {max_gap:.3f}% (Se requiere {cfg['EMA_GAP_PCT']}%)")
        print(f"    - Mom: {max_mom:.3f}% (Se requiere {cfg['MOMENTUM_MIN_PCT']}%)")
        print(f"    - Ticks que cumplieron TODO: {meets_all} / {len(precios)-55}")
        if meets_all == 0:
            print(f"    ⚠️ CONDICIONES MUY ESTRICTAS PARA EL MERCADO ACTUAL.")
        print("")

if __name__ == "__main__":
    analyze()
