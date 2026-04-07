import requests
import json
import os

# Claves de API (usar variables de entorno)
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

if not API_KEY or not API_SECRET:
    raise ValueError("Configura BINANCE_API_KEY y BINANCE_API_SECRET como variables de entorno")

# URL de la nueva API
BASE_URL = 'https://api.binance.com/api/v3/'

def get_account_balance():
    url = BASE_URL + 'account'
    headers = {'X-MBX-APIKEY': API_KEY}
    response = requests.get(url, headers=headers)
    return response.json()

if __name__ == '__main__':
    balance_data = get_account_balance()
    print(json.dumps(balance_data, indent=4))
    # Aquí podrías agregar lógica para guardar el balance en la base de datos o actualizar la plantilla /panel/binance/
