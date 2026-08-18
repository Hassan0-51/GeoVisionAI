from django.urls import path
from . import views

app_name = 'web_dashboard'

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('history/', views.HistoryView.as_view(), name='history'),
    path('history/delete/<int:pk>/', views.delete_history_item, name='delete_history'),
    path('settings/', views.AccountSettingsView.as_view(), name='settings'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('api/analysis-data/', views.AnalysisAPIView.as_view(), name='analysis_data'),
    path('api/charts/', views.ChartsAPIView.as_view(), name='charts_data'),
    path('api/map-layers/', views.MapLayersAPIView.as_view(), name='map_layers'),
    path('api/area-trend/', views.AreaTrendAPIView.as_view(), name='area_trend'),
]
