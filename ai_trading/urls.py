from django.urls import path
from . import views

app_name = 'ai_trading'

urlpatterns = [
    path('', views.dashboard_ia, name='dashboard'),
    path('api/estado/', views.EstadoEntrenamientoIAView.as_view(), name='estado'),
    path('api/top-estrategias/', views.TopEstrategiasView.as_view(), name='top-estrategias'),
    path('api/trades-recientes/', views.TradesRecientesIAView.as_view(), name='trades-recientes'),
    path('api/estrategia/<int:estrategia_id>/', views.EstadisticasEstrategiaView.as_view(), name='estadisticas-estrategia'),
]

