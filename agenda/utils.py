from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
import re
from .models import PerfilUsuario


def requiere_rol(*roles):
    def decorador(view_func):

        @wraps(view_func)
        def wrapper(request, *args, **kwargs):

            # Verificar que el usuario haya iniciado sesión
            if not request.user.is_authenticated:
                return redirect("agenda:login")

            try:
                # Obtener el rol directamente desde PerfilUsuario
                rol_usuario = request.user.perfil.rol.nombre.strip().upper()

            except (AttributeError, PerfilUsuario.DoesNotExist):

                print(
                    "DEBUG: El usuario no tiene PerfilUsuario o no tiene rol."
                )

                messages.error(
                    request,
                    "Tu cuenta no tiene un perfil o rol configurado en el sistema."
                )

                logout(request)

                return redirect("agenda:login")

            # Convertir los roles permitidos a mayúsculas
            roles_permitidos = [
                rol.strip().upper()
                for rol in roles
            ]

            # DEBUG temporal
            print("DEBUG USUARIO:", request.user.username)
            print("DEBUG ROL USUARIO:", rol_usuario)
            print("DEBUG ROLES PERMITIDOS:", roles_permitidos)

            # Comprobar si el rol del usuario está permitido
            if rol_usuario not in roles_permitidos:

                print("DEBUG: ACCESO DENEGADO")

                messages.error(
                    request,
                    "No tienes permisos para acceder a esta sección."
                )

                return redirect("agenda:dashboard")

            print("DEBUG: ACCESO AUTORIZADO")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorador


def validar_password(password):

    if len(password) < 8:
        return "La contraseña debe tener mínimo 8 caracteres"

    if not re.search(r"[A-Z]", password):
        return "Debe contener al menos una mayúscula"

    if not re.search(r"[a-z]", password):
        return "Debe contener al menos una minúscula"

    if not re.search(r"[0-9]", password):
        return "Debe contener al menos un número"

    return None