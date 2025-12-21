$ErrorActionPreference = "Stop"

# CREA ENTORNO VIRTUAL Y ASEGURA PIP, LUEGO INSTALA DEPENDENCIAS.

if (!(Test-Path ".venv")) {
  python -m venv .venv
}

$py = ".\\.venv\\Scripts\\python.exe"

# EN ALGUNAS DISTRIBUCIONES PORTABLES, EL VENV PUEDE QUEDAR SIN PIP (ensurepip roto).
# REGLA: SI NO EXISTE EL PAQUETE pip EN site-packages, SE BOOTSTRAPEA CON get-pip.py.
$pipDir = ".\\.venv\\Lib\\site-packages\\pip"
if (!(Test-Path $pipDir)) {
  $tmp = Join-Path $env:TEMP "get-pip.py"
  Invoke-WebRequest -UseBasicParsing https://bootstrap.pypa.io/get-pip.py -OutFile $tmp | Out-Null
  & $py $tmp
}

& $py -m pip --version

& $py -m pip install -r requirements.txt

if (!(Test-Path ".env")) {
  Copy-Item "env.example" ".env"
}

Write-Host "Listo. Activa el entorno con: .\\.venv\\Scripts\\activate"


