from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Sum, Avg
from django.utils import timezone
from datetime import timedelta
from gestion_riesgo.models import Cuenta, OperacionDeriv, BalanceDerivSnapshot
from subscriptions.models import Tenant, Suscripcion, Usuario, LogAuditoria, Plan


def is_admin(user):
    return user.is_staff


def admin_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("admin_panel:dashboard")
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_staff:
            login(request, user)
            nxt = request.GET.get("next", "/admin-panel/")
            return redirect(nxt)
        else:
            return render(request, "admin_panel/login.html", {"error": "Credenciales inválidas o no tienes acceso de staff."})
    return render(request, "admin_panel/login.html")


def admin_logout(request):
    logout(request)
    return redirect("admin_panel:login")


@user_passes_test(is_admin, login_url="/admin-panel/login/")
def admin_dashboard(request):
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    total_cuentas = Cuenta.objects.count()
    total_operaciones = OperacionDeriv.objects.count()
    ops_hoy = OperacionDeriv.objects.filter(created_at__gte=today_start).count()
    ops_semana = OperacionDeriv.objects.filter(created_at__gte=week_ago).count()
    total_tenants = Tenant.objects.count()
    total_usuarios = Usuario.objects.count()
    total_suscripciones = Suscripcion.objects.count()
    susc_activas = Suscripcion.objects.filter(estado=Suscripcion.Estado.ACTIVA).count()
    logs_recientes = LogAuditoria.objects.order_by("-fecha")[:50]

    wins = OperacionDeriv.objects.filter(resultado=OperacionDeriv.Resultado.GANANCIA).count()
    losses = OperacionDeriv.objects.filter(resultado=OperacionDeriv.Resultado.PERDIDA).count()
    winrate = round((wins / total_operaciones * 100), 1) if total_operaciones > 0 else 0

    ops_recientes = OperacionDeriv.objects.select_related("cuenta").order_by("-created_at")[:20]

    balances = BalanceDerivSnapshot.objects.order_by("-epoch")[:10]

    contexto = {
        "total_cuentas": total_cuentas,
        "total_operaciones": total_operaciones,
        "ops_hoy": ops_hoy,
        "ops_semana": ops_semana,
        "total_tenants": total_tenants,
        "total_usuarios": total_usuarios,
        "total_suscripciones": total_suscripciones,
        "susc_activas": susc_activas,
        "wins": wins,
        "losses": losses,
        "winrate": winrate,
        "logs_recientes": logs_recientes,
        "ops_recientes": ops_recientes,
        "balances": balances,
    }
    return render(request, "admin_panel/dashboard.html", contexto)


@user_passes_test(is_admin, login_url="/admin-panel/login/")
def admin_cuentas(request):
    cuentas = Cuenta.objects.all().order_by("-id")
    return render(request, "admin_panel/cuentas.html", {"cuentas": cuentas})


@user_passes_test(is_admin, login_url="/admin-panel/login/")
def admin_operaciones(request):
    ops = OperacionDeriv.objects.select_related("cuenta").order_by("-created_at")[:100]
    return render(request, "admin_panel/operaciones.html", {"operaciones": ops})


@user_passes_test(is_admin, login_url="/admin-panel/login/")
def admin_suscripciones(request):
    subs = Suscripcion.objects.select_related("tenant", "plan").order_by("-fecha_inicio")[:100]
    return render(request, "admin_panel/suscripciones.html", {"suscripciones": subs})


@user_passes_test(is_admin, login_url="/admin-panel/login/")
def admin_tenants(request):
    tenants = Tenant.objects.all().order_by("-fecha_creacion")
    return render(request, "admin_panel/tenants.html", {"tenants": tenants})


@user_passes_test(is_admin, login_url="/admin-panel/login/")
def admin_logs(request):
    logs = LogAuditoria.objects.select_related("usuario", "tenant").order_by("-fecha")[:100]
    return render(request, "admin_panel/logs.html", {"logs": logs})
