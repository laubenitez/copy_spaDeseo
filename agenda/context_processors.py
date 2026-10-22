from .models import Notificacion


def notificaciones_usuario(request):
    """
    Comparte las notificaciones con las plantillas
    de todas las secciones del sistema.
    """
    if not request.user.is_authenticated:
        return {
            "notificaciones": [],
            "notificaciones_no_leidas": 0,
        }

    notificaciones = Notificacion.objects.filter(
        destinatario=request.user
    ).order_by("-fecha_creacion")

    return {
        "notificaciones": notificaciones[:10],
        "notificaciones_no_leidas": notificaciones.filter(
            leida=False
        ).count(),
    }


def preferencias_accesibilidad(request):
    """
    Comparte las preferencias de accesibilidad del usuario
    con las plantillas de Spa Deseo.
    """
    if not request.user.is_authenticated:
        return {
            "preferencias_accesibilidad": None,
        }

    preferencias = getattr(
        request.user,
        "preferencias_spa",
        None
    )

    return {
        "preferencias_accesibilidad": preferencias,
    }