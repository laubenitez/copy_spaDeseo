from datetime import timedelta
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from drf_spectacular.extensions import OpenApiAuthenticationExtension  # Importar extensión

class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related('user').get(key=key)
        except model.DoesNotExist:
            raise AuthenticationFailed({'error': 'Token inválido', 'is_authenticated': False})

        if not token.user.is_active:
            raise AuthenticationFailed({'error': 'Usuario inactivo', 'is_authenticated': False})

        time_elapsed = timezone.now() - token.created
        if time_elapsed > timedelta(hours=24):
            token.delete()
            raise AuthenticationFailed({'error': 'El Token ha expirado', 'is_authenticated': False})

        return (token.user, token)


# Registro explícito para Swagger / OpenAPI
class ExpiringTokenScheme(OpenApiAuthenticationExtension):
    target_class = 'agenda.authentication.ExpiringTokenAuthentication'  # Ajusta la ruta si tu archivo tiene otro nombre
    name = 'expiringTokenAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'Token de autenticación con expiración (Ejemplo: Token 9944b09199c62bcf9418ad846d0d4bb864520416)',
        }