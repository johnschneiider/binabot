import asyncio
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bot_deriv.settings")

import django

django.setup()

from integracion_deriv.client import DerivWebsocketClient


async def main():
    client = DerivWebsocketClient()
    try:
        respuesta = await client.ping()
        print("Ping respuesta:", respuesta)
    finally:
        await client.cerrar()


if __name__ == "__main__":
    asyncio.run(main())

