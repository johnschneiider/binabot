import requests
import json

# Claves de API
API_KEY = 'Dbchp0j5NEZ1WI3q1onLnvEiblKkdJ1TbvdhKe8GMlqxESdUf16XL25x47Un4hxI'
API_SECRET = 'Te6BgIeyAQMFpEsVWgckQBEUIk8vKfcWjzbzoUyOK3pEPBCpP9WBtPuUkIdtMA6a'

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
