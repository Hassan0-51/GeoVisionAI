from django.urls import path
from django.contrib.auth import views as auth_views
from .views import register_view
from accounts import views
urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    # path('dashboard/', dashboard_view, name='dashboard'),
]
