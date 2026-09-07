from rest_framework import permissions
from .models import PerfilUsuario


class TieneRolDB(permissions.BasePermission):
    """
    Comprueba el rol del usuario mediante PerfilUsuario.
    """

    def has_permission(self, request, view):

        if not request.user or not request.user.is_authenticated:
            return False

        try:
            rol = request.user.perfil.rol.nombre
        except (AttributeError, PerfilUsuario.DoesNotExist):
            return False

        if request.method in permissions.SAFE_METHODS:
            return rol in [
                "ADMINISTRADOR",
                "CLIENTE",
                "MANICURISTA"
            ]

        return rol == "ADMINISTRADOR"


class EsAdministrador(permissions.BasePermission):

    def has_permission(self, request, view):

        if not request.user or not request.user.is_authenticated:
            return False

        try:
            return request.user.perfil.rol.nombre == "ADMINISTRADOR"
        except (AttributeError, PerfilUsuario.DoesNotExist):
            return False


class EsCliente(permissions.BasePermission):

    def has_permission(self, request, view):

        if not request.user or not request.user.is_authenticated:
            return False

        try:
            return request.user.perfil.rol.nombre == "CLIENTE"
        except (AttributeError, PerfilUsuario.DoesNotExist):
            return False


class EsManicurista(permissions.BasePermission):

    def has_permission(self, request, view):

        if not request.user or not request.user.is_authenticated:
            return False

        try:
            return request.user.perfil.rol.nombre == "MANICURISTA"
        except (AttributeError, PerfilUsuario.DoesNotExist):
            return False


class IsStaffOrReadOnly(permissions.BasePermission):
    """
    Lectura para usuarios autenticados.
    Modificación solamente para ADMINISTRADOR.
    """

    def has_permission(self, request, view):

        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in permissions.SAFE_METHODS:
            return True

        try:
            return request.user.perfil.rol.nombre == "ADMINISTRADOR"
        except (AttributeError, PerfilUsuario.DoesNotExist):
            return False