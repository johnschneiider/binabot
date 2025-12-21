from __future__ import annotations

"""
BOOTSTRAP DE SITE-PACKAGES PARA ENTORNOS "PORTABLE/EMBEDDED" EN WINDOWS.

CONTEXTO:
- EN ALGUNAS INSTALACIONES DE PYTHON (PORTABLES) NO SE AÑADE AUTOMÁTICAMENTE
  `Lib/site-packages` NI EL "USER SITE" A `sys.path`.
- ESO IMPIDE IMPORTAR DEPENDENCIAS (DJANGO, WEBSOCKETS, NUMPY) INCLUSO SI ESTÁN INSTALADAS.

REGLA:
- ESTE ARCHIVO NO PERTENECE A LA LÓGICA DEL BOT. SOLO GARANTIZA QUE EL ENTORNO
  PUEDA RESOLVER PAQUETES DE PYTHON DE FORMA ESTÁNDAR.
"""

import os
import sys
from pathlib import Path


def _agregar_si_existe(ruta: str) -> None:
    if ruta and ruta not in sys.path and os.path.isdir(ruta):
        sys.path.append(ruta)

# SI ESTAMOS EN UN ENTORNO VIRTUAL, NO TOCAMOS sys.path.
# POR QUÉ:
# - EL OBJETIVO DEL VENV ES AISLAR DEPENDENCIAS. INYECTAR SITE-PACKAGES GLOBALES ROMPE ESA GARANTÍA.
base_prefix = getattr(sys, "base_prefix", sys.prefix)
en_venv = (sys.prefix != base_prefix)

if not en_venv:
    try:
        import site  # noqa: WPS433

        _agregar_si_existe(site.getusersitepackages())
        for p in getattr(site, "getsitepackages", lambda: [])():
            _agregar_si_existe(p)
    except Exception:
        # SI FALLA `site`, SE USAN HEURÍSTICAS.
        pass

# HEURÍSTICA: <python_root>/Lib/site-packages
python_root = Path(sys.executable).resolve().parent
if not en_venv:
    _agregar_si_existe(str(python_root / "Lib" / "site-packages"))


