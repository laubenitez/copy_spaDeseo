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
            if not request.user.is_authenticated:
                return redirect("agenda:login")

            try:
                rol_usuario = request.user.perfil.rol.nombre.strip().upper()
            except (AttributeError, PerfilUsuario.DoesNotExist):
                # RED DE SEGURIDAD: Si está autenticado pero no tiene perfil, 
                # se lo creamos automáticamente aquí mismo para evitar bucles y cierres de sesión forzados.
                try:
                    from agenda.models import Rol
                    rol_cliente, _ = Rol.objects.get_or_create(nombre='CLIENTE')
                    perfil, _ = PerfilUsuario.objects.get_or_create(user=request.user, defaults={'rol': rol_cliente})
                    if not perfil.rol:
                        perfil.rol = rol_cliente
                        perfil.save()
                    rol_usuario = request.user.perfil.rol.nombre.strip().upper()
                except Exception:
                    messages.error(request, "Tu cuenta no tiene un perfil o rol configurado en el sistema.")
                    logout(request)
                    return redirect("agenda:login")

            roles_permitidos = [rol.strip().upper() for rol in roles]

            if rol_usuario not in roles_permitidos:
                messages.error(request, "No tienes permisos para acceder a esta sección.")
                return redirect("agenda:login")

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