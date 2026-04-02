"""
Trading views - DEPRECATED
Este archivo se mantiene solo para compatibilidad con BalanceGlobal.
El sistema Forex ha sido desactivado.
"""

from django.shortcuts import render

def dashboard(request):
    """Dashboard Forex - DESACTIVADO"""
    return render(request, 'trading/dashboard_disabled.html')
