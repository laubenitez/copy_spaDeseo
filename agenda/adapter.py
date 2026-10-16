import hashlib
import hmac
import secrets
import time

import requests

from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.shortcuts import redirect
from django.urls import reverse

from agenda.models import (
    PerfilUsuario,
    Rol,
    Clientes,
    PreferenciasUsuario,
)


class MySocialAccountAdapter(DefaultSocialAccountAdapter):

    # =========================================================
    # GENERAR Y ENVIAR CÓDIGO DE SEGURIDAD
    # =========================================================

    
    def _iniciar_verificacion(self, request, user):

        print(
            "VERIFICACION: comprobando preferencias del usuario",
            user.pk,
            flush=True
        )

        preferencias, creada = PreferenciasUsuario.objects.get_or_create(
            user=user
        )

        print(
            "VERIFICACION: activa =",
            preferencias.verificacion_adicional,
            flush=True
        )

        if not preferencias.verificacion_adicional:
            print(
                "VERIFICACION: verificación desactivada",
                flush=True
            )
            return False

        if not user.email:
            print(
                "VERIFICACION: el usuario no tiene correo",
                flush=True
            )
            messages.error(
                request,
                "Tu cuenta necesita un correo electrónico "
                "para verificar el acceso."
            )
            raise ImmediateHttpResponse(
                redirect("agenda:login")
            )

        codigo = str(secrets.randbelow(900000) + 100000)

        try:
            enviado = send_mail(
                subject="Código de seguridad - Spa Deseo",
                message=(
                    f"Hola {user.first_name or user.get_username()},\n\n"
                    f"Tu código de seguridad es: {codigo}\n\n"
                    "Este código vence en cinco minutos. "
                    "Si no intentaste iniciar sesión, ignora este mensaje."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )

            print(
                "VERIFICACION: resultado del envío =",
                enviado,
                flush=True
            )

            if enviado != 1:
                raise RuntimeError(
                    "No se pudo confirmar el envío del correo."
                )

        except Exception as error:
            print(
                "VERIFICACION: error al enviar correo =",
                repr(error),
                flush=True
            )

            messages.error(
                request,
                "No pudimos enviar el código de seguridad. "
                "Inténtalo nuevamente más tarde."
            )

            raise ImmediateHttpResponse(
                redirect("agenda:login")
            )

        request.session.pop("logueado", None)
        request.session.pop("usuario_verificacion_id", None)
        request.session.pop("codigo_verificacion", None)
        request.session.pop("codigo_verificacion_expira", None)
        request.session.pop("intentos_verificacion", None)

        request.session["usuario_verificacion_id"] = user.pk
        request.session["codigo_verificacion"] = hashlib.sha256(
            codigo.encode("utf-8")
        ).hexdigest()
        request.session["codigo_verificacion_expira"] = time.time() + 300
        request.session["intentos_verificacion"] = 0
        request.session.modified = True

        messages.info(
            request,
            "Enviamos un código de seguridad a tu correo. "
            "Introdúcelo para continuar."
        )

        raise ImmediateHttpResponse(
            redirect("agenda:verificar_codigo")
        )


    def _asegurar_perfil(self, user, sociallogin=None):

        rol_cliente = Rol.objects.filter(
            nombre__iexact="CLIENTE"
        ).first()

        if not rol_cliente:
            rol_cliente = Rol.objects.create(
                nombre="CLIENTE",
                descripcion="Cliente registrado por Google"
            )

        perfil, _ = PerfilUsuario.objects.get_or_create(
            user=user
        )

        # No reemplazar roles ya asignados.
        if not perfil.rol:
            perfil.rol = rol_cliente
            perfil.save(update_fields=["rol"])

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

        # Crear o actualizar el registro adicional del cliente.
        if perfil.rol and perfil.rol.nombre.strip().upper() == "CLIENTE":

            cliente, creado = Clientes.objects.get_or_create(
                user=user,
                defaults={
                    "nombre": nombre,
                    "apellido": apellido,
                    "telefono": "Por registrar",
                    "email": email,
                    "password": "",
                }
            )

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

            # Descargar la foto de Google solo si no hay una guardada.
            if foto_google and not cliente.foto_perfil:
                try:
                    respuesta = requests.get(
                        foto_google,
                        timeout=10
                    )
                    respuesta.raise_for_status()

                    cliente.foto_perfil.save(
                        f"google_{user.pk}.jpg",
                        ContentFile(respuesta.content),
                        save=True
                    )

                except requests.RequestException:
                    # Un fallo de la imagen no debe bloquear el acceso.
                    pass

        return perfil

    # =========================================================
    # REGISTRO NUEVO CON GOOGLE
    # =========================================================

    def save_user(self, request, sociallogin, form=None):

        user = super().save_user(
            request,
            sociallogin,
            form=form
        )

        self._asegurar_perfil(user, sociallogin)

        # La cuenta ya se creó, pero todavía no debe acceder al panel.
        self._iniciar_verificacion(request, user)

        return user

    # =========================================================
    # INICIO DE SESIÓN CON UNA CUENTA GOOGLE EXISTENTE
    # =========================================================

    def pre_social_login(self, request, sociallogin):

        print(
            "GOOGLE: entró a pre_social_login",
            flush=True
        )

        print(
            "GOOGLE: cuenta existente =",
            sociallogin.is_existing,
            flush=True
        )

        if sociallogin.is_existing:
            user = sociallogin.user

            print(
                "GOOGLE: usuario ID =",
                user.pk,
                flush=True
            )

            self._asegurar_perfil(user, sociallogin)

            print(
                "GOOGLE: perfil asegurado; iniciando verificación",
                flush=True
            )

            self._iniciar_verificacion(request, user)

    def on_authentication_error(
        self,
        request,
        provider,
        error=None,
        exception=None,
        extra_context=None
    ):
        messages.error(
            request,
            "No pudimos completar el inicio de sesión con Google."
        )
        return redirect("agenda:login")
