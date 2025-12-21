# Bot Cuantitativo Deriv (Django)

Arquitectura institucional mínima y modular:

- `vector_variables`: **EL MERCADO** (vector de estado \(x\)).
- `vector_pesos`: **LA ESTRATEGIA** (vector de pesos \(w\)).
- `gestion_riesgo`: **EL RIESGO** (innegociable).

## Requisitos

- Python 3.11+ recomendado

## Instalación

1. Crear entorno virtual e instalar dependencias (Windows PowerShell):

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\.venv\Scripts\activate
```

2. Crear tu `.env` basado en `env.example`:

```bash
copy env.example .env
```

3. Ejecutar el stream en una sola terminal (sin Celery, sin multiproceso).
   Por defecto el comando **NO corre indefinidamente**:

```bash
python manage.py deriv_stream --max-ticks 2000 --max-segundos 300
```

## Señal central

La decisión se basa en:

\[
\tilde{s} = w^\top x
\]

- Si \(\tilde{s} \ge UMBRAL\_COMPRA\) → **COMPRA**
- Si \(\tilde{s} \le UMBRAL\_VENTA\) → **VENTA**
- En caso contrario → **NO OPERAR**


