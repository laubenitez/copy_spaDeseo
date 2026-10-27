
from django.utils import translation


class PreferenciasIdiomaMiddleware:
    """Activa el idioma guardado en las preferencias del usuario autenticado."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        idioma_anterior = translation.get_language()

        idioma = "es"

        if request.user.is_authenticated:
            try:
                idioma_guardado = request.user.preferencias_spa.idioma

                if idioma_guardado in ("es", "en"):
                    idioma = idioma_guardado

            except Exception:
                idioma = "es"

        translation.activate(idioma)
        request.LANGUAGE_CODE = idioma

        try:
            response = self.get_response(request)
            response.headers["Content-Language"] = idioma
            return response
        finally:
            translation.activate(idioma_anterior)
