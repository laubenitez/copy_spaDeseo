from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from rest_framework.authtoken.views import obtain_auth_token
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Admin Django
    path('admin/', admin.site.urls),

    # Autenticación API Token & DRF
    path('api/auth/', include('rest_framework.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('api/api-token-auth/', obtain_auth_token, name='api_token_auth'),

    # Documentación OpenAPI / Swagger / ReDoc
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Rutas de la App (Vistas HTML + API del Router)
    # DEBE IR AL FINAL porque maneja path('')
    path('', include('agenda.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)