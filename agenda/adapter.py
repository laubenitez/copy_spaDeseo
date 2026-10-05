from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.shortcuts import redirect
from django.core.files.base import ContentFile

from agenda.models import PerfilUsuario, Rol, Clientes

import requests


class MySocialAccountAdapter(DefaultSocialAccountAdapter):

    def _asegurar_perfil(self, user, sociallogin=None):

        # =====================================================
        # 1. OBTENER O CREAR ROL CLIENTE
        # =====================================================

        rol_cliente = Rol.objects.filter(
            nombre__iexact="CLIENTE"
        ).first()

        if not rol_cliente:
            rol_cliente = Rol.objects.create(
                nombre="CLIENTE",
                descripcion="Cliente registrado por Google"
            )

        # =====================================================
        # 2. OBTENER O CREAR PERFIL DE USUARIO
        # =====================================================

        perfil, _ = PerfilUsuario.objects.get_or_create(
            user=user
        )

        # Solo asignamos CLIENTE si no tiene rol.
        # Así NO sobrescribimos MANICURISTA o ADMINISTRADOR.
        if not perfil.rol:
            perfil.rol = rol_cliente
            perfil.save(update_fields=["rol"])

        # =====================================================
        # 3. DATOS DE GOOGLE
        # =====================================================

        extra_data = {}

        if sociallogin:
            try:
                extra_data = sociallogin.account.extra_data or {}
            except Exception:
                extra_data = {}

        nombre = (
            extra_data.get("given_name")
            or user.first_name
            or user.username
        )

        apellido = (
            extra_data.get("family_name")
            or user.last_name
            or ""
        )

        email = (
            extra_data.get("email")
            or user.email
            or ""
        )

        foto_google = (
            extra_data.get("picture")
            or extra_data.get("profile_picture")
            or ""
        )

        # =====================================================
        # 4. SOLO CLIENTES
        # =====================================================

        if perfil.rol.nombre.strip().upper() == "CLIENTE":

            cliente, creado = Clientes.objects.get_or_create(
                user=user,
                defaults={
                    "nombre": nombre,
                    "apellido": apellido,
                    "telefono": "Por registrar",
                    "email": email,
                    "password": ""
                }
            )

            # =================================================
            # 5. ACTUALIZAR DATOS
            # =================================================

            cambios = []

            if nombre and cliente.nombre != nombre:
                cliente.nombre = nombre
                cambios.append("nombre")

            if cliente.apellido != apellido:
                cliente.apellido = apellido
                cambios.append("apellido")

            if email and cliente.email != email:
                cliente.email = email
                cambios.append("email")

            if cambios:
                cliente.save(update_fields=cambios)

            # =================================================
            # 6. GUARDAR FOTO DE GOOGLE
            # =================================================

            if foto_google and not cliente.foto_perfil:

                try:
                    respuesta = requests.get(
                        foto_google,
                        timeout=10
                    )

                    if respuesta.status_code == 200:

                        nombre_archivo = (
                            f"google_{user.id}.jpg"
                        )

                        cliente.foto_perfil.save(
                            nombre_archivo,
                            ContentFile(respuesta.content),
                            save=True
                        )

                except requests.RequestException:
                    # Si falla la foto, NO bloqueamos el login.
                    pass

        return perfil

    # =========================================================
    # USUARIO NUEVO DE GOOGLE
    # =========================================================

    def save_user(self, request, sociallogin, form=None):

        user = super().save_user(
            request,
            sociallogin,
            form=form
        )

        self._asegurar_perfil(
            user,
            sociallogin
        )

        return user

    # =========================================================
    # USUARIO EXISTENTE QUE ENTRA CON GOOGLE
    # =========================================================

    def pre_social_login(self, request, sociallogin):

        if sociallogin.is_existing:

            self._asegurar_perfil(
                sociallogin.user,
                sociallogin
            )

    # =========================================================
    # ERROR DE GOOGLE
    # =========================================================

    def on_authentication_error(
        self,
        request,
        provider,
        error=None,
        exception=None,
        extra_context=None
    ):
        return redirect("agenda:login")

