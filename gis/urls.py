"""
URL configuration for gis project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from gis import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('dashboard/', include('web_dashboard.urls')),
    path('', views.index,name='home'),
    path('academic_request', views.academic_request,name='academic_request'),
    path('analysis', views.analysis,name='analysis'),
    path('documentation', views.documentation,name='documentation'),
    path('api_documentation', views.api_documentation,name='api_documentation'),
    path('api_integration', views.api_integration,name='api_integration'),
    path('blogs', views.blogs,name='blogs'),
    path('case_studies', views.case_studies,name='case_studies'),
    path('research_paper', views.research_paper,name='research_paper'),
    path('tutorials', views.tutorials,name='tutorials'),
    path('delhi_lahore', views.delhi_lahore,name='delhi_lahore'),
    path('faisalabad_industrial', views.faisalabad_industrial,name='faisalabad_industrial'),
    path('karachi_research', views.karachi_research,name='karachi_research'),
    path('lahore_2023', views.lahore_2023,name='lahore_2023'),
    path('punjab_forestry', views.punjab_forestry,name='punjab_forestry'),
    path('rawalpindi_smart', views.rawalpindi_smart,name='rawalpindi_smart'),
    path('contact_sales', views.contact_sales,name='contact_sales'),
    path('cookies_policy', views.cookies_policy,name='cookies_policy'),
    path('custom_models', views.custom_models,name='custom_models'),
    path('data_catalog', views.data_catalog,name='data_catalog'),
    path('delhi_lahore', views.delhi_lahore,name='delhi_lahore'),
    path('enterprise', views.enterprise,name='enterprise'),
    path('faisalabad_industrial', views.faisalabad_industrial,name='faisalabad_industrial'),
    path('faqs', views.faqs,name='faqs'),
    path('forgot_password', views.forgot_password,name='forgot_password'),
    path('getting_started', views.getting_started,name='getting_started'),
    path('gis_export', views.gis_export,name='gis_export'),
    path('model_library', views.model_library,name='model_library'),
    path('privacy_policy', views.privacy_policy,name='privacy_policy'),
    path('support', views.support,name='support'),
    path('temporal_analysis', views.temporal_analysis,name='temporal_analysis'),
    path('terms', views.terms,name='terms'),
    path('understanding_result', views.understanding_result,name='understanding_result'),
    path('upgrade_plan', views.upgrade_plan,name='upgrade_plan'),
    path('verify_academic', views.verify_academic,name='verify_academic'),
    path('help', views.help,name='help'),
    path('temporal-results/<uuid:result_id>/', views.temporal_results, name='temporal_results'),
    path('current-results/<uuid:result_id>/', views.current_results, name='current_results'),
    path('api/temporal-data/<uuid:result_id>/', views.get_temporal_data, name='get_temporal_data'),
    path('api/temporal-data/<uuid:result_id>/<int:year>/<str:season>/', views.get_temporal_data, name='get_temporal_data_detail'),
    path('api/rgb-image/<uuid:result_id>/<int:year>/<str:season>/', views.get_rgb_image, name='get_rgb_image'),
    path('api/mask-image/<uuid:result_id>/<int:year>/<str:season>/', views.get_mask_image, name='get_mask_image'),
    path('api/chart-image/<uuid:result_id>/<str:chart_type>/', views.get_chart_image, name='get_chart_image'),
    path('api/new-image/<int:year>/<str:season>/', views.get_new_image, name='get_new_image'),
    path('api/new-image-bounds/<int:year>/<str:season>/', views.get_new_image_bounds, name='get_new_image_bounds'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
