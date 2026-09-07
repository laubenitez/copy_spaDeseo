from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
import re


def requiere_rol(*roles):
    def decorador(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("agenda:login")

            try:
                # Obtenemos el rol y lo limpiamos de espacios y mayúsculas/minúsculas
                rol_usuario = request.user.perfil.rol.nombre.strip().upper()
            except (AttributeError, Exception) as e:
                print(f"DEBUG: Error al obtener el perfil o rol: {e}")
                messages.error(
                    request,
                    "Tu cuenta no tiene un perfil o rol configurado en el sistema."
                )
                # IMPORTANTE: Cerramos sesión para evitar bucles infinitos de redirección
                logout(request)
                return redirect("agenda:login")

            # Normalizamos los roles permitidos que pasamos por parámetro
            roles_permitidos = [r.strip().upper() for r in roles]

            # Validación flexible utilizando correctamente la variable 'rol_usuario'
            autorizado = False
            for r in roles_permitidos:
                if rol_usuario == r or rol_usuario == r.rstrip('S'):  # Soporta plurales comunes
                    autorizado = True
                    break

            if not autorizado:
                messages.error(
                    request,
                    "No tienes permisos para acceder a esta sección."
                )
                return redirect("agenda:dashboard")

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