"""
Chat bot que usa OpenCode CLI para responder mensajes del usuario.
Ejecutar: python gestion_riesgo/management/commands/chat_bot.py
OpenCode tiene acceso completo al proyecto: puede leer, editar y ejecutar comandos.
"""
import time
import os
import sys
import re
import subprocess

# Asegurar que el directorio raíz del proyecto esté en sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')

import django
django.setup()

from gestion_riesgo.models import ChatMessage

# Directorio del proyecto donde opencode tiene contexto
PROJECT_DIR = _project_root

# ──────────────────────────────────────────────
# Utilidades
# ──────────────────────────────────────────────

def strip_ansi(text: str) -> str:
    """Elimina códigos ANSI de color/cursor del output del terminal."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def get_pending_messages(last_id: int):
    """Devuelve mensajes del usuario más nuevos que last_id."""
    return ChatMessage.objects.filter(
        id__gt=last_id,
        emisor="usuario"
    ).order_by("created_at")


def save_response(mensaje: str):
    """Guarda la respuesta de opencode directamente en la DB."""
    ChatMessage.objects.create(mensaje=mensaje, emisor="opencode")
    print(f"[CHAT] Respuesta guardada ({len(mensaje)} chars)", flush=True)


def call_opencode(mensaje: str) -> str:
    """
    Llama a opencode run '<mensaje>' --dir <proyecto> y devuelve el texto de respuesta.
    Timeout: 120 segundos (opencode puede tardar si hace cambios en archivos).
    """
    try:
        result = subprocess.run(
            ["opencode", "run", mensaje, "--dir", PROJECT_DIR],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=PROJECT_DIR,
            encoding="utf-8",
            errors="replace"
        )
        output = result.stdout or ""
        if result.returncode != 0 and result.stderr:
            output += "\n" + result.stderr
        clean = strip_ansi(output).strip()
        return clean if clean else "(OpenCode no devolvió respuesta)"
    except subprocess.TimeoutExpired:
        return "OpenCode tardó demasiado (>120s). El proceso puede seguir en segundo plano."
    except FileNotFoundError:
        return "Error: opencode no encontrado. Verifica que esté instalado con 'npm i -g opencode'."
    except Exception as e:
        return f"Error llamando a OpenCode: {e}"


# ──────────────────────────────────────────────
# Loop principal
# ──────────────────────────────────────────────

def main():
    last_id = ChatMessage.objects.order_by("-id").values_list("id", flat=True).first() or 0
    print(f"[CHAT BOT] Iniciado con OpenCode {PROJECT_DIR}", flush=True)
    print(f"[CHAT BOT] Último mensaje ID: {last_id}", flush=True)
    print(f"[CHAT BOT] Monitoreando mensajes cada 3s...", flush=True)

    while True:
        try:
            pendientes = get_pending_messages(last_id)

            for msg in pendientes:
                print(f"[CHAT] Usuario: {msg.mensaje}", flush=True)

                # Marcar como leído
                msg.leido = True
                msg.save(update_fields=["leido"])

                # Notificar que está procesando
                save_response("⏳ Procesando tu solicitud con OpenCode...")

                # Llamar a opencode
                respuesta = call_opencode(msg.mensaje)

                # Guardar respuesta real
                save_response(respuesta)
                last_id = ChatMessage.objects.order_by("-id").values_list("id", flat=True).first() or last_id

            if not pendientes:
                # Actualizar last_id por si hubo mensajes de opencode propios
                nuevo_max = ChatMessage.objects.order_by("-id").values_list("id", flat=True).first()
                if nuevo_max and nuevo_max > last_id:
                    last_id = nuevo_max

            time.sleep(3)

        except Exception as e:
            print(f"[CHAT ERROR] {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
