from datetime import timedelta
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related('user').get(key=key)
        except model.DoesNotExist:
            raise AuthenticationFailed({'error': 'Token inválido', 'is_authenticated': False})

        if not token.user.is_active:
            raise AuthenticationFailed({'error': 'Usuario inactivo', 'is_authenticated': False})

        # Calcular si el token tiene más de 24 horas de vida
        time_elapsed = timezone.now() - token.created
        if time_elapsed > timedelta(hours=24):
            # Elimina el token expirado de la BD para mantenerla limpia
            token.delete()
            raise AuthenticationFailed({'error': 'El Token ha expirado', 'is_authenticated': False})

        return (token.user, token)