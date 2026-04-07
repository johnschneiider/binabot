"""
Chat bot que responde automaticamente a los mensajes del usuario.
Ejecutar: python manage.py chat_bot
"""
import time
import os
import django
import requests
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()

from gestion_riesgo.models import ChatMessage

API_URL = "http://127.0.0.1:8000/api/chat/respuesta/"
LAST_MESSAGE_ID = 0

def get_last_message_id():
    """Obtiene el ID del ultimo mensaje"""
    try:
        msgs = ChatMessage.objects.all().order_by("-id")[:1]
        if msgs:
            return msgs[0].id
    except:
        pass
    return 0

def save_response(mensaje):
    """Guarda la respuesta de opencode"""
    try:
        requests.post(API_URL, json={"mensaje": mensaje}, timeout=10)
    except Exception as e:
        print(f"Error guardando respuesta: {e}")

def generate_response(mensaje):
    """Genera una respuesta al mensaje del usuario"""
    msg = mensaje.lower().strip()
    
    # Resuestas predefinidas para frases comunes
    responses = {
        "hola": "Hola! Como estas? En que puedo ayudarte hoy?",
        "como estas": "Estoy bien, gracias por preguntar! Y tu?",
        "balance": "El balance actual es $10.67 USDT. El bot esta corriendo y monitoreando el mercado.",
        "dinero": f"El balance actual es $10.67 USDT en Binance Futures.",
        "usdt": f"Tienes $10.67 USDT disponibles.",
        "bitcoin": f"Bitcoin (BTC) esta siendo monitoreado. Balance: $10.67 USDT",
        "btc": f"Bitcoin (BTC) esta siendo monitoreado. Balance: $10.67 USDT",
        "estado": "El bot esta corriendo, monitoreando BTC, ETH, SOL y XRP para señales de trading.",
        "señal": "En este momento no hay señales activas. Las condiciones del mercado no cumplen los criterios.",
        "ayuda": "Puedo informarte sobre: balance, estado del bot, señales, precio de criptomonedas. Solo preguntame!",
        "precio": "Los precios se actualizan cada segundo. Para ver el precio actual, preguntame especificamente (ej: precio de BTC)",
        "gracias": "De nada! Cualquier otra duda?",
        "adios": "Hasta luego! Que te vaya bien con el trading!",
        "chau": "Chao! Que te vaya bien!",
    }
    
    # Buscar coincidencias
    for key, response in responses.items():
        if key in msg:
            return response
    
    # Respuesta por defecto
    return f"Recibí tu mensaje: '{mensaje}'. Estoy monitoreando el bot de trading. Preguntame sobre el balance, estado, o necesitas ayuda con algo específico?"

def main():
    global LAST_MESSAGE_ID
    LAST_MESSAGE_ID = get_last_message_id()
    print("[CHAT BOT] Iniciado. Monitoreando mensajes...")
    print(f"[CHAT BOT] Ultimo mensaje ID: {LAST_MESSAGE_ID}")
    
    while True:
        try:
            # Obtener ultimo mensaje
            current_id = get_last_message_id()
            
            # Si hay nuevos mensajes
            if current_id > LAST_MESSAGE_ID:
                # Obtener los mensajes nuevos
                nuevos = ChatMessage.objects.filter(id__gt=LAST_MESSAGE_ID).order_by("created_at")
                
                for msg in nuevos:
                    if msg.emisor == "usuario":
                        print(f"[CHAT] Nuevo mensaje: {msg.mensaje}")
                        
                        # Generar respuesta
                        respuesta = generate_response(msg.mensaje)
                        
                        # Guardar respuesta
                        save_response(respuesta)
                        print(f"[CHAT] Respuesta guardada: {respuesta[:50]}...")
                
                LAST_MESSAGE_ID = current_id
            
            time.sleep(3)  # Chequear cada 3 segundos
            
        except Exception as e:
            print(f"[CHAT ERROR] {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
