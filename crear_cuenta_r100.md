# Crear Cuenta para R_100

## Problema
El dashboard está intentando mostrar datos de R_100 pero no existe una cuenta para ese símbolo en la base de datos.

## Solución: Crear cuenta R_100 manualmente

```bash
cd /var/www/vitalmix.com.co/app
source .venv/bin/activate

python manage.py shell -c "
from gestion_riesgo.models import Cuenta
from django.conf import settings

# Verificar si ya existe
cuenta_r100 = Cuenta.objects.filter(simbolo='R_100').first()
if cuenta_r100:
    print(f'Cuenta R_100 ya existe (ID: {cuenta_r100.id})')
else:
    # Crear cuenta R_100 basada en la configuración
    cuenta_r10 = Cuenta.objects.filter(simbolo='R_10').first()
    
    if cuenta_r10:
        # Crear R_100 con valores similares a R_10
        cuenta_r100 = Cuenta.objects.create(
            simbolo='R_100',
            balance_deriv=cuenta_r10.balance_deriv or 0.0,
            moneda_deriv=cuenta_r10.moneda_deriv or 'USD',
            capital_inicial=cuenta_r10.capital_inicial or getattr(settings, 'CAPITAL_INICIAL', 100.0),
            capital_actual=cuenta_r10.capital_actual or getattr(settings, 'CAPITAL_INICIAL', 100.0),
            max_capital_historico=cuenta_r10.max_capital_historico or getattr(settings, 'CAPITAL_INICIAL', 100.0),
            bloqueado=False,
            riesgo_motivo=None,
        )
        print(f'Cuenta R_100 creada (ID: {cuenta_r100.id})')
    else:
        # Si no hay R_10, crear con valores por defecto
        capital_inicial = getattr(settings, 'CAPITAL_INICIAL', 100.0)
        cuenta_r100 = Cuenta.objects.create(
            simbolo='R_100',
            balance_deriv=0.0,
            moneda_deriv='USD',
            capital_inicial=capital_inicial,
            capital_actual=capital_inicial,
            max_capital_historico=capital_inicial,
            bloqueado=False,
            riesgo_motivo=None,
        )
        print(f'Cuenta R_100 creada (ID: {cuenta_r100.id}) con capital inicial: {capital_inicial}')
"
```

## Verificar que se creó correctamente

```bash
python manage.py shell -c "
from gestion_riesgo.models import Cuenta
for simbolo in ['R_10', 'R_100']:
    cuenta = Cuenta.objects.filter(simbolo=simbolo).first()
    if cuenta:
        print(f'{simbolo}: ID={cuenta.id}, Balance={cuenta.balance_deriv}, Capital={cuenta.capital_actual}')
    else:
        print(f'{simbolo}: No existe')
"
```

## Nota Importante

**El bot `deriv_stream` solo trabaja con UN símbolo a la vez.** Actualmente está configurado para R_10.

Para que R_100 también reciba ticks, necesitarías:
1. **Opción 1**: Ejecutar el bot dos veces (una para cada símbolo) - NO recomendado
2. **Opción 2**: Modificar el bot para que maneje múltiples símbolos simultáneamente
3. **Opción 3**: Por ahora, crear la cuenta R_100 para que el dashboard no falle, pero solo R_10 mostrará datos reales

La cuenta R_100 se creará pero no recibirá ticks hasta que el bot sea modificado para manejar múltiples símbolos.
