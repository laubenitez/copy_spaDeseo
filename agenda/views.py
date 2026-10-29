import os
import re
import json
from django.contrib.auth import logout as auth_logout
import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime, date, time, timedelta
from django.utils.timezone import now
from django.contrib.sessions.models import Session
import requests
from django.core.validators import validate_email
from django.utils import translation
from django.db.models import Case, When, Value, IntegerField

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.db.models import Sum, Avg, Max, Min, Q, ProtectedError
from django.views.decorators.http import require_POST, require_http_methods, require_GET
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
# Django REST Framework & Spectacular
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.exceptions import ValidationError
from drf_spectacular.utils import extend_schema
from django.db.models import Prefetch
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.mail import send_mail
from PIL import Image, UnidentifiedImageError

# Importaciones locales explícitas
from .models import (
    Citas, Clientes, Manicurista, Administrador, Servicios, Inventario, MovimientoInventario, Pagos, Recibo,
    Gastos, Resena, SolicitudSoporte, PortafolioManicurista,  PreferenciasUsuario, Descuentos, Notificacion, PerfilUsuario, MensajeContacto
)
from .serializador import (
    ClientesSerializer, ManicuristaSerializer, ServiciosSerializer,
    CitasSerializer, InventarioSerializer, MovimientoInventarioSerializer, PagosSerializer,
    ReciboSerializer, GastosSerializer, ResenaSerializer,
)
from .notificaciones_utils import (
    notificar_cita_agendada,
    notificar_cita_modificada,
    notificar_cita_cancelada,
    notificar_resena_pendiente,
    crear_recibo_y_notificar,
    notificar_inventario_bajo
)
from .permissions import TieneRolDB, IsStaffOrReadOnly, EsAdministrador, PuedeGestionarSuPerfilCliente
from .utils import validar_password, requiere_rol
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
import hashlib
import hmac
import secrets
import time as time_module



logger = logging.getLogger(__name__)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Cerrar sesión de la API",
        description="Elimina el token del usuario actual.",
        responses={200: dict}
    )
    def post(self, request):
        request.user.auth_token.delete()
        return Response(
            {"message": "Sesión cerrada correctamente. Token destruido."},
            status=status.HTTP_200_OK
        )



# Vistas para las APIs
class ClientesViewSet(viewsets.ModelViewSet):
    authentication_classes = [
        SessionAuthentication,
        TokenAuthentication,
    ]

    permission_classes = [
        IsAuthenticated,
        PuedeGestionarSuPerfilCliente,
    ]

    serializer_class = ClientesSerializer

    # Limitar las operaciones disponibles desde esta API.
    # No permitir crear ni eliminar clientes desde este endpoint.
    http_method_names = [
        'get',
        'put',
        'patch',
        'head',
        'options',
    ]

    def get_queryset(self):
        # Cada usuario autenticado solo puede consultar
        # el perfil de cliente asociado a su propia cuenta.
        return Clientes.objects.filter(
            user=self.request.user
        )



class ManicuristaViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]


    queryset = Manicurista.objects.all()
    serializer_class = ManicuristaSerializer


class ServiciosViewSet(viewsets.ModelViewSet):
    authentication_classes = [
        SessionAuthentication,
        TokenAuthentication,
    ]

    queryset = Servicios.objects.all()
    serializer_class = ServiciosSerializer

    # Combinamos IsAuthenticated para obligar a usar token, e IsStaffOrReadOnly para el rol
    permission_classes = [IsAuthenticated, IsStaffOrReadOnly, TieneRolDB]

    # =========================================================================
    # ENDPOINT 1: DASHBOARD DE ESTADÍSTICAS (GET /api/servicios/dashboard/)
    # =========================================================================
    @extend_schema(
        summary="Obtener métricas y estadísticas del dashboard de servicios",
        responses={200: dict}  # Indica que devuelve un objeto JSON personalizado
    )
    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        # Mapeo y conteo de estados en la BD
        total_servicios = self.queryset.count()
        activos = self.queryset.filter(estado="Activo").count()
        inactivos = self.queryset.filter(estado="Inactivo").count()

        # Operaciones matemáticas directas en el motor de base de datos
        metricas_financieras = self.queryset.aggregate(
            recaudacion_total=Sum('precio'),
            costo_promedio=Avg('precio'),
            servicio_mas_caro=Max('precio'),
            servicio_mas_barato=Min('precio')
        )

        return Response({
            "contadores": {
                "total_registrados": total_servicios,
                "servicios_activos": activos,
                "servicios_inactivos": inactivos,
            },
            "finanzas": {
                "suma_total_costos": metricas_financieras['recaudacion_total'] or 0,
                "promedio_costo": round(metricas_financieras['costo_promedio'] or 0, 2),
                "precio_maximo": metricas_financieras['servicio_mas_caro'] or 0,
                "precio_minimo": metricas_financieras['servicio_mas_barato'] or 0
            }
        }, status=status.HTTP_200_OK)

    # =========================================================================
    # ENDPOINT 2: BÚSQUEDA AVANZADA MULTI-CAMPO (GET /api/servicios/buscar/?q=texto)
    # =========================================================================
    @extend_schema(
        summary="Buscar servicios por nombre o descripción",
        responses={200: dict}
    )
    @action(detail=False, methods=['get'])
    def buscar(self, request):
        query_texto = request.query_params.get('q', '').strip()

        if not query_texto:
            return Response(
                {"error": "Debes proporcionar un término de búsqueda en el parámetro 'q'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Filtro con compuerta lógica OR buscando coincidencias parciales (case-insensitive)
        resultados = self.queryset.filter(
            Q(nombre__icontains=query_texto) |
            Q(descripcion__icontains=query_texto)
        )

        serializer = self.get_serializer(resultados, many=True)

        return Response({
            "termino_buscado": query_texto,
            "total_coincidencias": resultados.count(),
            "resultados": serializer.data
        }, status=status.HTTP_200_OK)


    @extend_schema(
        summary="Lista de todos los servicios"
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class CitasViewSet(viewsets.ModelViewSet):
    queryset = Citas.objects.all()
    serializer_class = CitasSerializer

    authentication_classes = [
        SessionAuthentication,
        TokenAuthentication,
    ]

    permission_classes = [
        IsAuthenticated,
        TieneRolDB,
    ]

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'create']:
            permissions = [IsAuthenticated]
        else:
            permissions = [
                IsAuthenticated,
                TieneRolDB,
            ]

        return [permission() for permission in permissions]

    def perform_create(self, serializer):
        try:
            # Buscar el cliente vinculado a la sesión actual.
            cliente = Clientes.objects.filter(
                user=self.request.user
            ).first()

            if cliente is None:
                raise ValidationError({
                    "detail": (
                        "No existe un perfil de cliente asociado "
                        "a tu usuario. Inicia sesión con la cuenta "
                        "correcta o verifica tu perfil."
                    )
                })

            # Asignar el cliente automáticamente.
            with transaction.atomic():
                serializer.save(cliente=cliente)

        except IntegrityError as exc:
            raise ValidationError({
                "detail": (
                    "No se pudo completar la reserva. "
                    "Verifica que el horario esté disponible "
                    "y que los datos de la cita sean correctos."
                )
            }) from exc

    @extend_schema(
        summary="Lista de todas las citas"
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        return Citas.objects.filter(
            cliente__user=self.request.user
        ).select_related(
            'cliente',
            'manicurista',
            'servicios',
        )



class InventarioViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAdminUser, EsAdministrador]


    queryset = Inventario.objects.all()
    serializer_class = InventarioSerializer

    @extend_schema(
        summary="Lista del inventario"
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

class PagosViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated, TieneRolDB]

    queryset = Pagos.objects.all()
    serializer_class = PagosSerializer

    @extend_schema(
        summary="Lista de todos los pagos"
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

class ReciboViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAdminUser, EsAdministrador]
    queryset = Recibo.objects.all()
    serializer_class = ReciboSerializer

    @extend_schema(
        summary="Lista de todos los recibos"
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

class GastosViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAdminUser, EsAdministrador]


    queryset = Gastos.objects.all()
    serializer_class = GastosSerializer

    @extend_schema(
        summary="Lista de todos los gastos"
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)



class ResenaViewSet(viewsets.ModelViewSet):
    serializer_class = ResenaSerializer

    authentication_classes = [
        SessionAuthentication,
        TokenAuthentication,
    ]

    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return Resena.objects.filter(
            cita__cliente__user=self.request.user
        ).select_related(
            'cita',
            'cita__cliente',
            'cita__servicios',
        ).order_by('-fecha_creacion')

    def perform_create(self, serializer):
        cita = serializer.validated_data['cita']

        # Verificar que la cita pertenezca a la clienta autenticada.
        if cita.cliente.user_id != self.request.user.id:
            raise ValidationError({
                'cita': 'No puedes reseñar una cita de otra clienta.'
            })

        # Evitar reseñar citas que todavía no se han completado.
        if cita.estado != 'completada':
            raise ValidationError({
                'cita': 'Solo puedes reseñar citas completadas.'
            })

        serializer.save()

    @extend_schema(summary='Lista de mis reseñas')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


@login_required(login_url="agenda:login")
@require_POST
def solicitar_desactivacion_cuenta(request):
    """
    Permite desactivar su cuenta a clientes y manicuristas,
    pero impide que el administrador desactive la suya.
    """

    usuario = request.user

    # Identificar el rol del usuario.
    perfil = getattr(usuario, "perfil", None)
    rol = ""

    if perfil and perfil.rol:
        rol = perfil.rol.nombre.strip().upper()

    # Impedir que el administrador desactive su propia cuenta.
    if rol == "ADMINISTRADOR":
        messages.error(
            request,
            "El administrador no puede desactivar su propia cuenta."
        )
        return redirect("agenda:ajustes")

    # Verificar que el usuario haya confirmado la operación.
    if request.POST.get("confirmar_desactivacion") != "si":
        messages.error(
            request,
            "Debes confirmar la solicitud para desactivar tu cuenta."
        )
        return redirect("agenda:ajustes")

    # Desactivar la cuenta sin eliminar sus datos.
    usuario.is_active = False
    usuario.save(update_fields=["is_active"])

    # Cerrar la sesión actual.
    auth_logout(request)

    # Limpiar los datos auxiliares de sesión.
    request.session.pop("logueado", None)
    request.session.flush()

    messages.success(
        request,
        "Tu cuenta ha sido desactivada. "
        "Los registros relacionados no se han eliminado."
    )

    return redirect("agenda:login")


@login_required(login_url="agenda:login")
def ajustes(request):
    preferencias, creada = PreferenciasUsuario.objects.get_or_create(
        user=request.user
    )

    es_cliente = hasattr(request.user, "cliente")
    perfil = getattr(request.user, "perfil", None)
    es_administrador = (
        perfil is not None
        and perfil.rol is not None
        and perfil.rol.nombre.strip().upper() == "ADMINISTRADOR"
    )

    if request.method == "POST":
        preferencias.verificacion_adicional = (
            request.POST.get("verificacion_adicional") == "on"
        )

        if es_cliente:
            preferencias.recordatorios_whatsapp = (
                request.POST.get("recordatorios_whatsapp") == "on"
            )

        preferencias.permitir_comunicaciones = (
            request.POST.get("permitir_comunicaciones") == "on"
        )

        formato_fecha = request.POST.get("formato_fecha", "DMY")
        formato_hora = request.POST.get("formato_hora", "12")
        tamano_texto = request.POST.get("tamano_texto", "normal")
        contraste = request.POST.get("contraste", "estandar")
        animaciones = request.POST.get("animaciones", "activadas")
        modo_lectura = request.POST.get("modo_lectura", "desactivado")

        opciones_validas = {
            "formato_fecha": {"DMY", "MDY"},
            "formato_hora": {"12", "24"},
            "tamano_texto": {"normal", "grande", "pequeno"},
            "contraste": {"estandar", "alto"},
            "animaciones": {"activadas", "reducidas"},
            "modo_lectura": {"desactivado", "activado"},
        }

        valores_recibidos = {
            "formato_fecha": formato_fecha,
            "formato_hora": formato_hora,
            "tamano_texto": tamano_texto,
            "contraste": contraste,
            "animaciones": animaciones,
            "modo_lectura": modo_lectura,
        }

        if any(
            valor not in opciones_validas[campo]
            for campo, valor in valores_recibidos.items()
        ):
            messages.error(
                request,
                "No se pudieron guardar los ajustes porque hay opciones inválidas."
            )
        else:
            for campo, valor in valores_recibidos.items():
                setattr(preferencias, campo, valor)

            preferencias.save()

            messages.success(
                request,
                "Tus ajustes se guardaron correctamente."
            )

            return redirect("agenda:ajustes")

    tiene_contrasena = request.user.has_usable_password()
    cuenta_activa = request.user.is_active

    usa_google = False
    if hasattr(request.user, "socialaccount_set"):
        usa_google = request.user.socialaccount_set.filter(
            provider="google"
        ).exists()

    estado_seguridad_correcto = (
        cuenta_activa and (tiene_contrasena or usa_google)
    )

    contexto = {
        "preferencias": preferencias,
        "ultimo_acceso": request.user.last_login,
        "tiene_contrasena": tiene_contrasena,
        "cuenta_activa": cuenta_activa,
        "usa_google": usa_google,
        "estado_seguridad_correcto": estado_seguridad_correcto,
        "es_cliente": es_cliente,
        "es_administrador": es_administrador,
    }

    return render(request, "ajustes.html", contexto)

# ACTIVAR Y DESACTIVAR CUENTAS DE CLIENTES

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_POST
def desactivar_cliente_admin(request, id):
    try:
        cliente = get_object_or_404(
            Clientes.objects.select_related("user"),
            pk=id
        )

        if not cliente.user:
            messages.error(
                request,
                "Este cliente no tiene un usuario asociado."
            )
            return redirect("agenda:ver_cliente")

        if not cliente.user.is_active:
            messages.warning(
                request,
                f"La cuenta de {cliente.nombre} ya está desactivada."
            )
            return redirect("agenda:ver_cliente")

        cliente.user.is_active = False
        cliente.user.save(update_fields=["is_active"])

        messages.success(
            request,
            f"La cuenta de {cliente.nombre} fue desactivada correctamente."
        )

    except Exception as e:
        print(f"Error al desactivar cliente: {e}")
        messages.error(
            request,
            "Ocurrió un error al desactivar la cuenta del cliente."
        )

    return redirect("agenda:ver_cliente")


@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_POST
def activar_cliente_admin(request, id):
    try:
        cliente = get_object_or_404(
            Clientes.objects.select_related("user"),
            pk=id
        )

        if not cliente.user:
            messages.error(
                request,
                "Este cliente no tiene un usuario asociado."
            )
            return redirect("agenda:ver_cliente")

        if cliente.user.is_active:
            messages.warning(
                request,
                f"La cuenta de {cliente.nombre} ya está activa."
            )
            return redirect("agenda:ver_cliente")

        cliente.user.is_active = True
        cliente.user.save(update_fields=["is_active"])

        messages.success(
            request,
            f"La cuenta de {cliente.nombre} fue reactivada correctamente."
        )

    except Exception as e:
        print(f"Error al activar cliente: {e}")
        messages.error(
            request,
            "Ocurrió un error al activar la cuenta del cliente."
        )

    return redirect("agenda:ver_cliente")
def terminos_condiciones(request):
    return render(request, "terminos_condiciones.html")

@login_required(login_url="agenda:login")
@require_POST
def cerrar_sesiones_dispositivos(request):
    """
    Cierra las sesiones de Django pertenecientes al usuario actual,
    incluidas las abiertas en otros dispositivos.
    """

    usuario_id = str(request.user.pk)

    # Buscar las sesiones que todavía no han expirado.
    sesiones = Session.objects.filter(
        expire_date__gte=timezone.now()
    )

    # Identificar y eliminar las sesiones del usuario.
    for sesion in sesiones:
        try:
            datos_sesion = sesion.get_decoded()

            if datos_sesion.get("_auth_user_id") == usuario_id:
                sesion.delete()

        except (ValueError, TypeError):
            # Ignorar sesiones que no puedan decodificarse.
            continue

    # Cerrar también la sesión actual.
    auth_logout(request)

    messages.success(
        request,
        "Se cerraron las sesiones de tu cuenta. "
        "Inicia sesión nuevamente para continuar."
    )

    return redirect("agenda:login")


@login_required(login_url="agenda:login")
def cambiar_contrasena(request):
    if request.method == "POST":
        formulario = PasswordChangeForm(
            user=request.user,
            data=request.POST
        )

        if formulario.is_valid():
            usuario = formulario.save()

            # Mantiene la sesión iniciada después del cambio
            update_session_auth_hash(request, usuario)

            messages.success(
                request,
                "Tu contraseña se cambió correctamente."
            )

            return redirect("agenda:ajustes")

        messages.error(
            request,
            "No se pudo cambiar la contraseña. "
            "Revisa los campos e inténtalo nuevamente."
        )
    else:
        formulario = PasswordChangeForm(user=request.user)

    return render(
        request,
        "cambiar_contrasena.html",
        {"formulario": formulario}
    )


@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE", "MANICURISTA")
def soporte(request):

    if request.method == "POST":

        asunto = request.POST.get("asunto", "").strip()
        descripcion = request.POST.get("descripcion", "").strip()

        if not asunto or not descripcion:
            messages.error(
                request,
                "Debes completar el asunto y la descripción de la solicitud."
            )

            return redirect("agenda:soporte")

        # Obtener el rol real desde PerfilUsuario
        try:
            rol = request.user.perfil.rol.nombre.capitalize()
        except (AttributeError, PerfilUsuario.DoesNotExist):

            messages.error(
                request,
                "Tu usuario no tiene un rol asignado."
            )

            return redirect("agenda:login")

        # Obtener nombre del usuario
        nombre = request.user.get_full_name()

        if not nombre:
            nombre = request.user.username

        SolicitudSoporte.objects.create(
            usuario=request.user,
            nombre_solicitante=nombre,
            rol_solicitante=rol,
            asunto=asunto,
            descripcion=descripcion,
            estado="Pendiente"
        )

        messages.success(
            request,
            "Tu solicitud de soporte fue enviada correctamente."
        )

        return redirect("agenda:soporte")

    solicitudes = SolicitudSoporte.objects.filter(
        usuario=request.user
    ).order_by("-fecha_creacion")

    return render(
        request,
        "soporte.html",
        {
            "solicitudes": solicitudes
        }
    )


@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
def soporte_administrador(request):

    solicitudes = SolicitudSoporte.objects.all().order_by(
        "-fecha_creacion"
    )

    total = solicitudes.count()

    pendientes = solicitudes.filter(
        estado__in=["Pendiente", "En revisión"]
    ).count()

    resueltas = solicitudes.filter(
        estado="Resuelto"
    ).count()

    return render(
        request,
        "soporte_administrador.html",
        {
            "solicitudes": solicitudes,
            "total_solicitudes": total,
            "solicitudes_pendientes": pendientes,
            "solicitudes_resueltas": resueltas,
        }
    )


@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
def responder_solicitud_soporte(request, id):

    if request.method != "POST":
        return redirect("agenda:soporte_administrador")

    solicitud = get_object_or_404(
        SolicitudSoporte,
        id=id
    )

    respuesta = request.POST.get(
        "respuesta",
        ""
    ).strip()

    if not respuesta:

        messages.error(
            request,
            "Debes escribir una respuesta antes de resolver la solicitud."
        )

        return redirect("agenda:soporte_administrador")

    solicitud.respuesta = respuesta

    solicitud.estado = "Resuelto"

    solicitud.administrador_respuesta = request.user

    solicitud.fecha_resolucion = timezone.now()

    solicitud.save()

    messages.success(
        request,
        f"La solicitud #{solicitud.id:04d} fue resuelta correctamente."
    )

    return redirect("agenda:soporte_administrador")


from django.contrib import messages
from django.shortcuts import render, redirect

def index(request):
    # Procesar el formulario de contacto
    if request.method == "POST":
        nombre = request.POST.get("nombre", "").strip()
        correo = request.POST.get("correo", "").strip()
        asunto = request.POST.get("asunto", "").strip()
        mensaje = request.POST.get("mensaje", "").strip()

        if nombre and correo and asunto and mensaje:
            MensajeContacto.objects.create(
                nombre=nombre,
                correo=correo,
                asunto=asunto,
                mensaje=mensaje
            )

            messages.success(
                request,
                "¡Tu mensaje ha sido enviado con éxito! "
                "Nos pondremos en contacto pronto."
            )

            return redirect('/#contacto')

        messages.error(
            request,
            "Por favor, completa todos los campos obligatorios."
        )

    # Consultar información de la página principal
    servicios = Servicios.objects.filter(
        estado="Activo"
    ).order_by("nombre")

    resenas = Resena.objects.select_related(
        "cita__cliente"
    ).order_by("-fecha_creacion")[:6]

    contexto = {
        "servicios": servicios,
        "resenas": resenas,
    }

    return render(request, "index.html", contexto)


def sobre_nosotros(request):
    return render(request, "sobre_nosotros.html")

def lista_servicios(request):
    servicios = Servicios.objects.filter(estado="Activo").order_by("nombre")
    contexto = {
        "servicios": servicios,
    }
    return render(request, "catalogo_servicios.html", contexto)


@login_required(login_url="agenda:login")
@requiere_rol("MANICURISTA")
def citas_asignadas(request):
    """
    Muestra el listado de citas asignadas a la manicurista autenticada.
    Incluye optimización de consultas SQL (Anti N+1), control estricto
    de perfil y ordenamiento por estado, fecha y hora.
    """

    # 1. Validación de perfil asignado
    try:
        manicurista = Manicurista.objects.get(user=request.user)
    except Manicurista.DoesNotExist:
        messages.error(
            request,
            "Tu usuario no está vinculado a un perfil activo de manicurista."
        )
        return redirect("agenda:login")

    # 2. Consulta optimizada y ordenada por estado
    citas = (
        Citas.objects
        .filter(manicurista=manicurista)
        .select_related("cliente", "servicios")
        .annotate(
            orden_estado=Case(
                When(estado="programada", then=Value(1)),
                When(estado="en_proceso", then=Value(2)),
                When(estado="completada", then=Value(3)),
                When(estado="cancelada", then=Value(4)),
                default=Value(5),
                output_field=IntegerField(),
            )
        )
        .order_by("orden_estado", "fecha", "hora")
    )

    # 3. Comprobar si cada cliente permite recordatorios por WhatsApp
    for cita in citas:
        cita.recordatorios_whatsapp_activos = True

        if cita.cliente and cita.cliente.user:
            try:
                preferencias = cita.cliente.user.preferencias_spa
                cita.recordatorios_whatsapp_activos = (
                    preferencias.recordatorios_whatsapp
                )
            except PreferenciasUsuario.DoesNotExist:
                pass

    # 4. Contexto para la plantilla
    contexto = {
        "manicurista": manicurista,
        "citas": citas,
    }

    return render(
        request,
        "manicurista/citas_asignadas.html",
        contexto
    )





@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE", "MANICURISTA", "ADMINISTRADOR")
@transaction.atomic
def editar_perfil(request):
    """
    Edición de perfil unificada para Cliente, Manicurista y Administrador.
    """

    usuario = request.user

    try:
        rol = usuario.perfil.rol.nombre.strip().upper()
    except (AttributeError, PerfilUsuario.DoesNotExist):
        messages.error(
            request,
            "Error de autenticación: El usuario no posee un rol válido."
        )
        return redirect("agenda:login")

    # =========================================================
    # 1. OBTENER PERFIL SEGÚN EL ROL
    # =========================================================

    if rol == "CLIENTE":
        perfil = get_object_or_404(Clientes, user=usuario)

    elif rol == "MANICURISTA":
        perfil = get_object_or_404(Manicurista, user=usuario)

    elif rol == "ADMINISTRADOR":
        perfil = get_object_or_404(Administrador, user=usuario)

    else:
        messages.error(
            request,
            "No tienes permisos para editar este perfil."
        )
        return redirect("agenda:dashboard")

    # =========================================================
    # 2. GUARDAR CAMBIOS
    # =========================================================

    if request.method == "POST":

        nuevo_email = request.POST.get("email", "").strip()
        nuevo_nombre = request.POST.get("nombre", "").strip()
        nuevo_apellido = request.POST.get("apellido", "").strip()
        nuevo_telefono = request.POST.get("telefono", "").strip()

        # Fecha de nacimiento: solo aplica a clientes.
        nuevo_fecha_nacimiento = None

        if rol == "CLIENTE":
            fecha_recibida = request.POST.get("fecha_nacimiento", "").strip()

            if fecha_recibida:
                nuevo_fecha_nacimiento = parse_date(fecha_recibida)

                if nuevo_fecha_nacimiento is None:
                    messages.error(request, "Ingresa una fecha de nacimiento válida.")
                    return redirect("agenda:editar_perfil")

                if nuevo_fecha_nacimiento > timezone.localdate():
                    messages.error(
                        request,
                        "La fecha de nacimiento no puede ser futura."
                    )
                    return redirect("agenda:editar_perfil")


        # =====================================================
        # VALIDACIONES BÁSICAS
        # =====================================================

        if not nuevo_nombre:
            messages.error(request, "El nombre es obligatorio.")
            return redirect("agenda:editar_perfil")

        if not nuevo_apellido:
            messages.error(request, "El apellido es obligatorio.")
            return redirect("agenda:editar_perfil")

        if not nuevo_email:
            messages.error(request, "El correo electrónico es obligatorio.")
            return redirect("agenda:editar_perfil")

        if not nuevo_telefono:
            messages.error(request, "El teléfono es obligatorio.")
            return redirect("agenda:editar_perfil")

        # =====================================================
        # 3. VALIDAR QUE EL CORREO NO PERTENEZCA A OTRO USER
        # =====================================================

        correo_en_uso = (
            User.objects
            .filter(email__iexact=nuevo_email)
            .exclude(pk=usuario.pk)
            .exists()
        )

        if correo_en_uso:
            messages.error(
                request,
                "El correo electrónico ingresado ya está registrado por otro usuario."
            )
            return redirect("agenda:editar_perfil")

        # =====================================================
        # 4. MANEJO DE FOTO
        # =====================================================

        eliminar_foto = request.POST.get("eliminar_foto") == "true"
        foto = request.FILES.get("foto_perfil")

        if eliminar_foto:

            if perfil.foto_perfil:
                perfil.foto_perfil.delete(save=False)

            perfil.foto_perfil = None

        elif foto:

            ext = os.path.splitext(foto.name)[1].lower()

            if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
                messages.error(
                    request,
                    "Formato de imagen no permitido. Usa JPG, PNG o WEBP."
                )
                return redirect("agenda:editar_perfil")

            if perfil.foto_perfil:
                perfil.foto_perfil.delete(save=False)

            perfil.foto_perfil = foto

        # =====================================================
        # 5. ACTUALIZAR PERFIL
        # =====================================================

        try:

            perfil.nombre = nuevo_nombre
            perfil.apellido = nuevo_apellido
            perfil.telefono = nuevo_telefono
            perfil.email = nuevo_email
            if rol == "CLIENTE":
                perfil.fecha_nacimiento = nuevo_fecha_nacimiento
            perfil.save()

            # =================================================
            # 6. ACTUALIZAR USUARIO DE DJANGO
            # =================================================

            usuario.first_name = nuevo_nombre
            usuario.last_name = nuevo_apellido
            usuario.email = nuevo_email

            # IMPORTANTE:
            # No modificar usuario.username aquí.
            usuario.save(
                update_fields=[
                    "first_name",
                    "last_name",
                    "email"
                ]
            )

            # =================================================
            # 7. ACTUALIZAR SESIÓN
            # =================================================

            if "logueado" in request.session:

                request.session["logueado"]["nombre"] = nuevo_nombre
                request.session["logueado"]["apellido"] = nuevo_apellido
                request.session["logueado"]["email"] = nuevo_email
                request.session["logueado"]["rol"] = rol.capitalize()

                request.session.modified = True

            messages.success(
                request,
                "Perfil actualizado correctamente."
            )

            return redirect("agenda:editar_perfil")

        except IntegrityError:

            messages.error(
                request,
                "Error al guardar los datos. Intenta nuevamente."
            )

            return redirect("agenda:editar_perfil")

    # =========================================================
    # 8. CONTEXTO PARA EL TEMPLATE
    # =========================================================

    contexto = {
        "usuario": usuario,
        "perfil": perfil,
        "rol": rol,
    }

    return render(
        request,
        "cliente/editar_perfil.html",
        contexto
    )





def politica_privacidad(request):
    return render(request, "politica_privacidad.html")


def login(request):
    """
    Inicio de sesión de Spa Deseo.
    Si la verificación adicional está activa, solicita un código por correo.
    """

    if request.user.is_authenticated:
        return redirect("agenda:dashboard")

    if request.method != "POST":
        return render(request, "login.html")

    correo = request.POST.get("user", "").strip()
    clave = request.POST.get("password", "")

    if not correo or not clave:
        messages.error(
            request,
            "Debes ingresar el correo y la contraseña."
        )
        return redirect("agenda:login")

    # Buscar la cuenta por correo.
    try:
        usuario = User.objects.get(email__iexact=correo)
    except (User.DoesNotExist, User.MultipleObjectsReturned):
        messages.error(request, "Credenciales inválidas.")
        return redirect("agenda:login")

    # Validar la contraseña con el sistema de autenticación de Django.
    user = authenticate(
        request,
        username=usuario.get_username(),
        password=clave
    )

    if user is None:
        messages.error(request, "Credenciales inválidas.")
        return redirect("agenda:login")

    if not user.is_active:
        messages.error(request, "Tu cuenta está desactivada.")
        return redirect("agenda:login")

    # Comprobar que la cuenta tenga perfil y rol.
    try:
        perfil = user.perfil
    except (AttributeError, PerfilUsuario.DoesNotExist):
        messages.error(
            request,
            "Tu cuenta no tiene un perfil asignado."
        )
        return redirect("agenda:login")

    if not perfil.rol:
        messages.error(
            request,
            "Tu cuenta no tiene un rol asignado."
        )
        return redirect("agenda:login")

    # Consultar las preferencias individuales.
    preferencias, _ = PreferenciasUsuario.objects.get_or_create(
        user=user
    )

    # Si está activada la verificación adicional, enviar un código.
    if preferencias.verificacion_adicional:

        if not user.email:
            messages.error(
                request,
                "Tu cuenta necesita un correo electrónico "
                "para verificar el acceso."
            )
            return redirect("agenda:login")

        codigo = str(secrets.randbelow(900000) + 100000)

        try:
            enviado = send_mail(
                subject="Código de seguridad - Spa Deseo",
                message=(
                    f"Hola {user.first_name or user.get_username()},\n\n"
                    f"Tu código de seguridad es: {codigo}\n\n"
                    "Este código vence en cinco minutos. "
                    "Si no intentaste iniciar sesión, "
                    "ignora este mensaje."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )

            if enviado != 1:
                raise RuntimeError("No se pudo enviar el correo.")



        except Exception as error:
            print(
                "ERROR REAL AL ENVIAR EL CÓDIGO:",
                repr(error),
                flush=True
            )

            messages.error(
                request,
                "No pudimos enviar el código de seguridad. "
                "Verifica la configuración del correo e inténtalo "
                "nuevamente."
            )
            return redirect("agenda:login")


        # Todavía NO se inicia la sesión autenticada.
        # Solo se guarda la información temporal de verificación.
        request.session.pop("logueado", None)
        request.session.pop("usuario_verificacion_id", None)
        request.session.pop("codigo_verificacion", None)
        request.session.pop("codigo_verificacion_expira", None)
        request.session.pop("intentos_verificacion", None)

        request.session["usuario_verificacion_id"] = user.pk
        request.session["codigo_verificacion"] = hashlib.sha256(
            codigo.encode("utf-8")
        ).hexdigest()
        request.session["codigo_verificacion_expira"] = time_module.time() + 300
        request.session["intentos_verificacion"] = 0
        request.session.modified = True

        messages.info(
            request,
            "Enviamos un código a tu correo. "
            "Introdúcelo para continuar."
        )
        return redirect("agenda:verificar_codigo")

    # Si la verificación está desactivada, iniciar sesión normalmente.
    auth_login(request, user)

    request.session["logueado"] = {
        "id": user.pk,
        "nombre": user.first_name or user.get_username(),
        "apellido": user.last_name or "",
        "rol": perfil.rol.nombre.capitalize(),
        "email": user.email,
    }

    request.session.modified = True

    return redirect("agenda:dashboard")


def verificar_codigo(request):
    """
    Comprueba el código temporal antes de permitir el acceso al panel.
    """

    usuario_id = request.session.get("usuario_verificacion_id")
    codigo_guardado = request.session.get("codigo_verificacion")
    expiracion = request.session.get("codigo_verificacion_expira")

    # No permitir entrar si no existe una verificación pendiente.
    if not usuario_id or not codigo_guardado or not expiracion:
        messages.warning(
            request,
            "Primero inicia sesión con tu correo y contraseña."
        )
        return redirect("agenda:login")

    # Si venció el código, limpiar la verificación pendiente.
    if time_module.time() >= expiracion:
        request.session.pop("usuario_verificacion_id", None)
        request.session.pop("codigo_verificacion", None)
        request.session.pop("codigo_verificacion_expira", None)
        request.session.pop("intentos_verificacion", None)

        messages.error(
            request,
            "El código venció. Inicia sesión nuevamente "
            "para recibir otro."
        )
        return redirect("agenda:login")

    if request.method == "POST":
        codigo_ingresado = request.POST.get("codigo", "").strip()
        intentos = request.session.get("intentos_verificacion", 0)

        # Permitir como máximo cinco intentos.
        if intentos >= 5:
            request.session.pop("usuario_verificacion_id", None)
            request.session.pop("codigo_verificacion", None)
            request.session.pop("codigo_verificacion_expira", None)
            request.session.pop("intentos_verificacion", None)

            messages.error(
                request,
                "Superaste el número de intentos. "
                "Inicia sesión nuevamente."
            )
            return redirect("agenda:login")

        codigo_hash = hashlib.sha256(
            codigo_ingresado.encode("utf-8")
        ).hexdigest()

        if not hmac.compare_digest(codigo_hash, codigo_guardado):
            intentos += 1

            if intentos >= 5:
                request.session.pop("usuario_verificacion_id", None)
                request.session.pop("codigo_verificacion", None)
                request.session.pop("codigo_verificacion_expira", None)
                request.session.pop("intentos_verificacion", None)

                messages.error(
                    request,
                    "Superaste el número de intentos. "
                    "Inicia sesión nuevamente."
                )
                return redirect("agenda:login")

            request.session["intentos_verificacion"] = intentos
            request.session.modified = True

            messages.error(
                request,
                "El código es incorrecto. "
                f"Te quedan {5 - intentos} intentos."
            )
            return redirect("agenda:verificar_codigo")

        # Comprobar que la cuenta siga activa y conserve su perfil.
        try:
            user = User.objects.get(
                pk=usuario_id,
                is_active=True
            )
            perfil = user.perfil

            if not perfil.rol:
                raise PerfilUsuario.DoesNotExist

        except (
            User.DoesNotExist,
            AttributeError,
            PerfilUsuario.DoesNotExist,
        ):
            request.session.pop("usuario_verificacion_id", None)
            request.session.pop("codigo_verificacion", None)
            request.session.pop("codigo_verificacion_expira", None)
            request.session.pop("intentos_verificacion", None)

            messages.error(
                request,
                "No pudimos verificar tu cuenta. "
                "Inicia sesión nuevamente."
            )
            return redirect("agenda:login")

        # Consumir el código antes de iniciar la sesión autenticada.
        request.session.pop("usuario_verificacion_id", None)
        request.session.pop("codigo_verificacion", None)
        request.session.pop("codigo_verificacion_expira", None)
        request.session.pop("intentos_verificacion", None)

        backend = user.backend if hasattr(user, "backend") else "django.contrib.auth.backends.ModelBackend"
        auth_login(request, user, backend=backend)

        # Mantener la estructura de sesión que utiliza Spa Deseo.
        request.session["logueado"] = {
            "id": user.pk,
            "nombre": user.first_name or user.get_username(),
            "apellido": user.last_name or "",
            "rol": perfil.rol.nombre.capitalize(),
            "email": user.email,
        }

        request.session.modified = True

        messages.success(
            request,
            "Verificación completada. ¡Bienvenido/a!"
        )
        return redirect("agenda:dashboard")

    return render(request, "verificar_codigo.html")






@transaction.atomic
def register(request):

    # Redireccionar si el usuario ya está autenticado
    if request.user.is_authenticated:
        return redirect("agenda:dashboard")

    if request.method == "POST":

        # Recoger los datos del formulario
        password = request.POST.get("password", "")
        email = request.POST.get("email", "").strip().lower()
        nombre = request.POST.get("nombre", "").strip()
        apellido = request.POST.get("apellido", "").strip()
        telefono = request.POST.get("telefono", "").strip()

        datos = {
            "nombre": nombre,
            "apellido": apellido,
            "email": email,
            "telefono": telefono,
        }

        # Verificar términos y condiciones
        if not request.POST.get("terminos"):
            messages.error(
                request,
                "Debes aceptar los términos y condiciones."
            )
            return render(request, "register.html", datos)

        # Validar el formato del correo en el servidor
        try:
            validate_email(email)
        except ValidationError:
            messages.error(
                request,
                "Ingresa una dirección de correo electrónico válida."
            )
            return render(request, "register.html", datos)

        # Validar contraseña
        error = validar_password(password)

        if error:
            messages.error(request, error)
            return render(request, "register.html", datos)

        # Verificar que el correo no esté registrado
        if (
            User.objects.filter(username__iexact=email).exists()
            or User.objects.filter(email__iexact=email).exists()
        ):
            messages.error(
                request,
                "Ya existe una cuenta con ese correo."
            )
            return render(request, "register.html", datos)

        # Verificar que la API esté configurada
        api_key = getattr(
            settings,
            "EMAIL_VALIDATION_API_KEY",
            ""
        )

        if not api_key:
            messages.error(
                request,
                "El servicio de validación de correos no está "
                "configurado. Inténtalo más tarde."
            )
            return render(request, "register.html", datos)

        # Consultar la API para comprobar el correo
        try:
            respuesta = requests.post(
                "https://api.email-validation.org/v1/validate",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "email": email,
                    "timeout": 10,
                },
                timeout=20,
            )

            respuesta.raise_for_status()
            resultado = respuesta.json()
            estado_correo = resultado.get("status")

            # Solo continuar si la API devuelve "valid"
            if estado_correo == "invalid":
                messages.error(
                    request,
                    "El correo parece ser inválido. "
                    "Verifica la dirección e inténtalo nuevamente."
                )
                return render(request, "register.html", datos)

            if estado_correo != "valid":
                messages.warning(
                    request,
                    "No fue posible confirmar que el buzón exista. "
                    "Prueba con otra dirección de correo."
                )
                return render(request, "register.html", datos)

        except requests.exceptions.RequestException:
            messages.error(
                request,
                "No pudimos consultar el servicio de validación "
                "de correos. Inténtalo nuevamente más tarde."
            )
            return render(request, "register.html", datos)

        except (ValueError, TypeError):
            messages.error(
                request,
                "El servicio de validación devolvió una respuesta "
                "inesperada. Inténtalo nuevamente."
            )
            return render(request, "register.html", datos)

        # Crear la cuenta después de validar el correo
        try:

            # 1. Buscar el rol CLIENTE
            rol = Rol.objects.get(nombre="CLIENTE")

            # 2. Crear usuario Django
            user = User(
                username=email,
                email=email,
                first_name=nombre,
                last_name=apellido,
            )

            # 3. Guardar contraseña de forma segura
            user.set_password(password)
            user.save()

            # 4. Obtener el perfil creado por la señal
            perfil = PerfilUsuario.objects.get(user=user)
            perfil.rol = rol
            perfil.save()

            # 5. Crear información del cliente
            Clientes.objects.create(
                user=user,
                nombre=nombre,
                apellido=apellido,
                telefono=telefono,
                email=email,
            )

            messages.success(
                request,
                "Cuenta creada correctamente. "
                "Ahora puedes iniciar sesión."
            )

            return redirect("agenda:login")

        except Rol.DoesNotExist:
            messages.error(
                request,
                "El rol CLIENTE no existe en la base de datos."
            )
            return render(request, "register.html", datos)

        except Exception:
            # Registrar el error real en la terminal del servidor
            import logging
            logging.getLogger(__name__).exception(
                "Error al crear la cuenta de Spa Deseo."
            )

            messages.error(
                request,
                "Ocurrió un error al crear la cuenta. "
                "Inténtalo de nuevo."
            )
            return render(request, "register.html", datos)

    return render(request, "register.html")




@login_required(login_url="agenda:login")
def dashboard(request):
    preferencias_accesibilidad, _ = PreferenciasUsuario.objects.get_or_create(
        user=request.user
    )

    # =========================================================
    # 1. OBTENER O CREAR EL PERFIL DEL USUARIO
    # =========================================================

    perfil_usuario, _ = PerfilUsuario.objects.get_or_create(
        user=request.user
    )

    # =========================================================
    # 2. SI NO TIENE ROL, SE ASIGNA CLIENTE
    #    Esto permite que los usuarios de Google entren
    #    automáticamente como CLIENTE.
    # =========================================================

    if not perfil_usuario.rol:
        rol_cliente, _ = Rol.objects.get_or_create(
            nombre="CLIENTE",
            defaults={
                "descripcion": "Cliente registrado en el sistema"
            }
        )

        perfil_usuario.rol = rol_cliente
        perfil_usuario.save(update_fields=["rol"])

    rol = perfil_usuario.rol.nombre.strip().upper()

    # =========================================================
    # NOTIFICACIONES DEL USUARIO AUTENTICADO
    # =========================================================
    notificaciones = Notificacion.objects.filter(
        destinatario=request.user
    ).order_by("-fecha_creacion")[:10]

    notificaciones_no_leidas = Notificacion.objects.filter(
        destinatario=request.user,
        leida=False
    ).count()

    # Variables generales
    cliente = None
    manicurista_logueada = None
    citas = []
    servicios_disponibles = []
    manicuristas_disponibles = []

    # =========================================================
    # 3. CLIENTE
    # =========================================================

    if rol == "CLIENTE":

        cliente, creado = Clientes.objects.get_or_create(
            user=request.user,
            defaults={
                "nombre": request.user.first_name or request.user.username,
                "apellido": request.user.last_name or "",
                "email": request.user.email or "",
                "telefono": "Por registrar",
                "password": ""
            }
        )

        # -----------------------------------------------------
        # Sincronizar datos provenientes de Google/Django
        # -----------------------------------------------------

        cambios = []

        nombre_google = request.user.first_name or request.user.username
        apellido_google = request.user.last_name or ""
        email_google = request.user.email or ""

        if nombre_google and cliente.nombre != nombre_google:
            cliente.nombre = nombre_google
            cambios.append("nombre")

        if cliente.apellido != apellido_google:
            cliente.apellido = apellido_google
            cambios.append("apellido")

        if email_google and cliente.email != email_google:
            cliente.email = email_google
            cambios.append("email")

        if cambios:
            cliente.save(update_fields=cambios)

        # -----------------------------------------------------
        # Citas del cliente
        # -----------------------------------------------------

        citas = Citas.objects.filter(
            cliente=cliente
        ).select_related(
            "manicurista",
            "servicios"
        ).order_by(
            "-fecha",
            "-hora"
        )[:5]

        # -----------------------------------------------------
        # Datos para la sesión
        # -----------------------------------------------------

        foto = ""

        if cliente.foto_perfil:
            foto = cliente.foto_perfil.url

        request.session["logueado"] = {
            "id": request.user.id,
            "nombre": cliente.nombre,
            "apellido": cliente.apellido,
            "nombre_completo": f"{cliente.nombre} {cliente.apellido}".strip(),
            "email": cliente.email,
            "rol": rol.capitalize(),
            "foto": foto,
        }

        request.session.modified = True

        # -----------------------------------------------------
        # Si todavía no tiene teléfono
        # -----------------------------------------------------

        if not cliente.telefono or cliente.telefono == "Por registrar":

            messages.warning(
                request,
                "Por favor, completa tu número de teléfono para continuar."
            )

            return redirect("agenda:editar_perfil")

        contexto = {
            "rol": rol,
            "preferencias_accesibilidad": preferencias_accesibilidad,
            "cliente": cliente,
            "perfil": perfil_usuario,
            "citas": citas,
            "usuario": request.user,
            "notificaciones": notificaciones,
            "notificaciones_no_leidas": notificaciones_no_leidas,
        }

        return render(
            request,
            "dashboard_copy.html",
            contexto
        )

    # =========================================================
    # 4. MANICURISTA
    # =========================================================

    elif rol == "MANICURISTA":

        try:

            manicurista_logueada = Manicurista.objects.get(
                user=request.user
            )

        except Manicurista.DoesNotExist:

            messages.error(
                request,
                "No existe información de manicurista asociada a tu usuario."
            )

            return redirect("agenda:login")

        citas = Citas.objects.filter(
            manicurista=manicurista_logueada
        ).select_related(
            "cliente",
            "servicios"
        ).order_by(
            "-fecha",
            "-hora"
        )[:5]

        foto = ""

        if hasattr(manicurista_logueada, "foto_perfil") and manicurista_logueada.foto_perfil:
            foto = manicurista_logueada.foto_perfil.url

        request.session["logueado"] = {
            "id": request.user.id,
            "nombre": request.user.first_name or request.user.username,
            "apellido": request.user.last_name or "",
            "email": request.user.email or "",
            "rol": rol.capitalize(),
            "foto": foto,
        }

        request.session.modified = True

        contexto = {
            "rol": rol,
            "preferencias_accesibilidad": preferencias_accesibilidad,
            "perfil": perfil_usuario,
            "citas": citas,
            "manicurista": manicurista_logueada,
            "usuario": request.user,

            "notificaciones": notificaciones,
            "notificaciones_no_leidas": notificaciones_no_leidas,
        }

        return render(
            request,
            "dashboard_copy.html",
            contexto
        )

    # =========================================================
    # 5. ADMINISTRADOR
    # =========================================================

    elif rol == "ADMINISTRADOR":

        citas = Citas.objects.select_related(
            "cliente",
            "manicurista",
            "servicios"
        ).order_by(
            "-fecha",
            "-hora"
        )[:10]

        servicios_disponibles = Servicios.objects.filter(
            estado="Activo"
        )[:6]

        manicuristas_disponibles = Manicurista.objects.filter(
            estado="Activa"
        )[:6]

        request.session["logueado"] = {
            "id": request.user.id,
            "nombre": request.user.first_name or request.user.username,
            "apellido": request.user.last_name or "",
            "nombre_completo": request.user.get_full_name() or request.user.username,
            "email": request.user.email or "",
            "rol": rol.capitalize(),
        }

        request.session.modified = True

        contexto = {
            "usuario": request.user.get_full_name() or request.user.username,
            "rol": rol,
            "preferencias_accesibilidad": preferencias_accesibilidad,
            "perfil": perfil_usuario,
            "citas": citas,
            "servicios": servicios_disponibles,
            "manicuristas": manicuristas_disponibles,
            "cliente_id_logueado": None,

            "notificaciones": notificaciones,
            "notificaciones_no_leidas": notificaciones_no_leidas,
        }

        return render(
            request,
            "dashboard_copy.html",
            contexto
        )

    # =========================================================
    # 6. RESPALDO
    # =========================================================

    request.session["logueado"] = {
        "id": request.user.id,
        "nombre": request.user.first_name or request.user.username,
        "apellido": request.user.last_name or "",
        "email": request.user.email or "",
        "rol": rol.capitalize(),
    }

    request.session.modified = True

    contexto = {
        "rol": rol,
        "cliente": cliente,
        "preferencias_accesibilidad": preferencias_accesibilidad,
        "perfil": perfil_usuario,
        "citas": citas,
        "usuario": request.user,
        "notificaciones": notificaciones,
        "notificaciones_no_leidas": notificaciones_no_leidas,
    }

    return render(
        request,
        "dashboard_copy.html",
        contexto
    )


@login_required(login_url="agenda:login")
def logout(request):
    # Cerrar sesión nativa de Django
    auth_logout(request)

    # Eliminar la clave 'logueado' o limpiar la sesión por completo de forma segura
    request.session.pop("logueado", None)
    request.session.flush()

    messages.success(request, "Sesión cerrada correctamente.")

    return redirect("agenda:login")

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR", "MANICURISTA")
def ver_cliente(request):

    # Consultar los clientes y sus usuarios relacionados.
    clientes = Clientes.objects.filter(
        user__perfil__rol__nombre="CLIENTE"
    ).select_related("user").order_by("nombre")

    # Comprobar las preferencias de WhatsApp de cada cliente.
    for cliente in clientes:
        # Mantener el comportamiento predeterminado si no existen preferencias.
        cliente.recordatorios_whatsapp_activos = True

        if cliente.user:
            try:
                preferencias = cliente.user.preferencias_spa
                cliente.recordatorios_whatsapp_activos = (
                    preferencias.recordatorios_whatsapp
                )
            except PreferenciasUsuario.DoesNotExist:
                pass

    contexto = {
        "datos": clientes
    }

    return render(request, "cliente/clientes.html", contexto)


@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
def crear_cliente(request):
    if request.method == "POST":
        password = request.POST.get("password", "")
        email = request.POST.get("email", "").strip().lower()
        nombre = request.POST.get("nombre", "").strip()
        apellido = request.POST.get("apellido", "").strip()
        telefono = request.POST.get("telefono", "").strip()

        # 1. Validar que los campos obligatorios estén completos.
        if not all([password, email, nombre, apellido, telefono]):
            messages.error(
                request,
                "Todos los campos son obligatorios."
            )
            return redirect("agenda:crear_cliente")

        # 2. Validar el formato del correo.
        try:
            validate_email(email)
        except ValidationError:
            messages.error(
                request,
                "El formato del correo electrónico no es válido."
            )
            return redirect("agenda:crear_cliente")

        # 3. Validar la contraseña.
        error = validar_password(password)

        if error:
            messages.error(request, error)
            return redirect("agenda:crear_cliente")

        # 4. Verificar si el correo ya está registrado.
        if (
            User.objects.filter(username__iexact=email).exists()
            or User.objects.filter(email__iexact=email).exists()
        ):
            messages.error(
                request,
                "Ya existe un usuario registrado con ese correo."
            )
            return redirect("agenda:crear_cliente")

        # 5. Consultar la API externa de validación.
        api_key = os.environ.get("EMAIL_VALIDATION_API_KEY")

        if not api_key:
            messages.error(
                request,
                "La validación externa del correo no está configurada. "
                "Contacta al administrador del sistema."
            )
            return redirect("agenda:crear_cliente")

        try:
            respuesta = requests.post(
                "https://api.email-validation.org/v1/validate",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "email": email,
                    "timeout": 6,
                },
                timeout=10,
            )

            respuesta.raise_for_status()
            resultado = respuesta.json()
            estado_correo = resultado.get("status", "").lower()

        except requests.RequestException:
            messages.error(
                request,
                "No fue posible verificar el correo en este momento. "
                "Inténtalo nuevamente más tarde."
            )
            return redirect("agenda:crear_cliente")

        except ValueError:
            messages.error(
                request,
                "El servicio de validación devolvió una respuesta no válida."
            )
            return redirect("agenda:crear_cliente")

        # 6. Aceptar solamente correos confirmados como válidos.
        if estado_correo != "valid":
            if estado_correo == "invalid":
                mensaje = (
                    "El correo no parece existir o no puede recibir mensajes. "
                    "Verifica la dirección ingresada."
                )
            elif estado_correo == "catch_all":
                mensaje = (
                    "No se pudo confirmar que ese buzón específico exista. "
                    "Utiliza un correo que pueda verificarse."
                )
            elif estado_correo in ("spamtrap", "abuse", "do_not_mail"):
                mensaje = (
                    "El correo no puede aceptarse por motivos de seguridad "
                    "o entregabilidad."
                )
            else:
                mensaje = (
                    "No fue posible confirmar que el correo sea válido. "
                    "Revisa la dirección e inténtalo nuevamente."
                )

            messages.error(request, mensaje)
            return redirect("agenda:crear_cliente")

        # 7. Crear el usuario y su ficha solo si pasó las validaciones.
        try:
            with transaction.atomic():
                rol = Rol.objects.get(nombre="CLIENTE")

                user = User(
                    username=email,
                    email=email,
                    first_name=nombre,
                    last_name=apellido,
                )
                user.set_password(password)
                user.save()

                perfil, _ = PerfilUsuario.objects.get_or_create(
                    user=user
                )
                perfil.rol = rol
                perfil.save()

                Clientes.objects.create(
                    user=user,
                    nombre=nombre,
                    apellido=apellido,
                    telefono=telefono,
                    email=email,
                )

            messages.success(
                request,
                "Cliente creado correctamente."
            )
            return redirect("agenda:ver_cliente")

        except Rol.DoesNotExist:
            messages.error(
                request,
                "El rol CLIENTE no existe. Créalo primero."
            )
            return redirect("agenda:crear_cliente")

        except Exception:
            messages.error(
                request,
                "Ocurrió un error al crear el cliente. Inténtalo de nuevo."
            )
            return redirect("agenda:crear_cliente")

    return render(request, "cliente/crear_cliente.html")



@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")  # <--- Exclusivo para administradores
def eliminar_cliente(request, id):
    # Forzar petición POST para evitar vulnerabilidades CSRF por enlace
    if request.method != "POST":
        messages.error(request, "Método no permitido para eliminar registros.")
        return redirect("agenda:ver_cliente")

    try:
        with transaction.atomic():
            q = Clientes.objects.get(pk=id)
            nombre_cliente = f"{q.nombre} {q.apellido}"

            # Si el cliente tiene un usuario asociado, al borrar el User se borra en cascada
            if q.user:
                q.user.delete()
            else:
                q.delete()

            messages.success(request, f"Cliente '{nombre_cliente}' eliminado correctamente.")

    except IntegrityError:
        messages.error(
            request,
            "No se puede eliminar el cliente porque cuenta con citas u otros registros asociados."
        )
    except Clientes.DoesNotExist:
        messages.warning(request, "El cliente no existe.")
    except Exception:
        messages.error(request, "Ocurrió un error al intentar eliminar el cliente.")

    return redirect("agenda:ver_cliente")

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR", "CLIENTE")
def actualizar_cliente(request, id):
    try:
        q = Clientes.objects.get(pk=id)
    except Clientes.DoesNotExist:
        messages.error(request, "El cliente consultado no existe.")
        return redirect("agenda:ver_cliente")

    # Validación de Seguridad (Anti-IDOR): Un cliente solo puede editar su propio perfil
    rol_actual = request.user.perfil.rol.nombre.upper()
    if rol_actual == "CLIENTE" and q.user != request.user:
        messages.error(request, "No tienes permiso para modificar la información de otro cliente.")
        return redirect("agenda:dashboard")

    if request.method == "POST":
        try:
            with transaction.atomic():
                # 1. Limpieza de variables
                nombre = request.POST.get('nombre', '').strip()
                apellido = request.POST.get('apellido', '').strip()
                telefono = request.POST.get('telefono', '').strip()
                email = request.POST.get('email', '').strip()
                color_piel = request.POST.get('color_piel')

                # 2. Actualizar la ficha del cliente
                q.nombre = nombre
                q.apellido = apellido
                q.telefono = telefono
                q.email = email
                q.color_piel = color_piel
                q.save()

                # 3. Sincronizar el usuario de Django (User) si está vinculado
                if q.user:
                    q.user.first_name = nombre
                    q.user.last_name = apellido
                    q.user.email = email
                    q.user.username = email  # Mantiene consistencia si usas el correo como username
                    q.user.save()

            messages.success(request, "¡Cliente actualizado correctamente!")

            # Redirección según el rol que edita
            if rol_actual == "CLIENTE":
                return redirect("agenda:dashboard")
            return redirect("agenda:ver_cliente")

        except Exception:
            messages.error(request, "Ocurrió un error al actualizar el cliente.")
            return redirect("agenda:ver_cliente")

    contexto = {
        "datos": q
    }
    return render(request, "cliente/formulario_cliente.html", contexto)

@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
def crear_resena(request, cita_id):
    cita = get_object_or_404(Citas, id=cita_id)

    # 1. Validación de Seguridad (Anti-IDOR): La cita debe pertenecer al cliente logueado
    if cita.cliente.user != request.user:
        messages.error(request, "No tienes permiso para crear una reseña en esta cita.")
        return redirect("agenda:mis_citas")

    # 2. Solo se pueden reseñar citas completadas/realizadas
    if cita.estado.lower() != "completada":
        messages.warning(request, "Solo puedes calificar citas que hayan sido completadas.")
        return redirect("agenda:mis_citas")

    # 3. Evitar que una cita tenga más de una reseña
    if hasattr(cita, 'resena'):
        messages.warning(request, 'Esta cita ya tiene una reseña.')
        return redirect('agenda:mis_citas')

    if request.method == 'POST':
        calificacion = request.POST.get('calificacion')
        comentario = request.POST.get('comentario', '').strip()

        if not calificacion:
            messages.error(request, 'Debes seleccionar una calificación.')
            return render(request, 'cliente/crear_resena.html', {'cita': cita})

        # Validar que la calificación sea un número entre 1 y 5
        try:
            calificacion_num = int(calificacion)
            if calificacion_num < 1 or calificacion_num > 5:
                raise ValueError
        except ValueError:
            messages.error(request, 'La calificación debe ser un valor entero entre 1 y 5.')
            return render(request, 'cliente/crear_resena.html', {'cita': cita})

        # Crear la reseña de forma segura
        Resena.objects.create(
            cita=cita,
            calificacion=calificacion_num,
            comentario=comentario
        )

        messages.success(request, '¡Muchas gracias por tu reseña!')
        return redirect('agenda:mis_citas')

    return render(request, 'cliente/crear_resena.html', {'cita': cita})


@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
def mis_resenas(request):

    # 1. Obtención segura de la ficha del cliente
    try:
        cliente = Clientes.objects.get(user=request.user)
    except Clientes.DoesNotExist:
        messages.error(
            request,
            "No existe información de cliente asociada a tu usuario."
        )
        return redirect("agenda:login")

    # 2. Consultar reseñas con JOINs optimizados
    resenas = Resena.objects.filter(
        cita__cliente=cliente
    ).select_related(
        "cita",
        "cita__manicurista",
        "cita__servicios"
    ).order_by(
        "-cita__fecha",
        "-cita__hora"
    )

    # 3. Obtener las preferencias de fecha y hora
    try:
        preferencias = request.user.preferencias_spa
        formato_fecha = preferencias.formato_fecha
        formato_hora = preferencias.formato_hora
    except PreferenciasUsuario.DoesNotExist:
        formato_fecha = "DMY"
        formato_hora = "12"

    # 4. Enviar los datos a la plantilla
    return render(request, "cliente/mis_resenas.html", {
        "resenas": resenas,
        "formato_fecha": formato_fecha,
        "formato_hora": formato_hora,
    })


@requiere_rol("ADMINISTRADOR")
def ver_todas_resenas(request):
    try:
        # Robustez: Consulta segura de todas las reseñas ordenadas de la más nueva a la más antigua
        resenas = Resena.objects.all().order_by('-id')
    except DatabaseError:
        # Control específico ante fallos de base de datos
        resenas = []
        messages.error(request, "Ocurrió un error en la base de datos al intentar cargar las reseñas.")
    except Exception:
        # Control genérico ante eventualidades imprevistas
        resenas = []
        messages.error(request, "Ocurrió un error inesperado al cargar las reseñas.")

    contexto = {
        "datos": resenas
    }
    return render(request, "administrador/resenas.html", contexto)


# CRUD CITAS
@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
def mis_citas(request):

    # 1. Obtener el cliente asociado de forma segura
    cliente = Clientes.objects.filter(user=request.user).first()

    if not cliente:
        messages.warning(request, "No se encontró un perfil de cliente asociado a tu cuenta.")
        return redirect("agenda:login")

    # 2. Consultar citas con optimización de relaciones (select_related)
    citas = Citas.objects.filter(
        cliente=cliente
    ).select_related(
        'manicurista',
        'servicios',
        'resena' # Permite verificar cita.resena en el HTML sin consultas extra
    ).prefetch_related(
        'pagos'
    ).order_by('-fecha', '-hora')

    # Obtener las preferencias de fecha y hora
    try:
        preferencias = request.user.preferencias_spa
        formato_fecha = preferencias.formato_fecha
        formato_hora = preferencias.formato_hora
    except PreferenciasUsuario.DoesNotExist:
        formato_fecha = "DMY"
        formato_hora = "12"

    return render(request, "cliente/mis_citas.html", {
        "citas": citas,
        "formato_fecha": formato_fecha,
        "formato_hora": formato_hora,
    })


@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR", "CLIENTE")
def ver_citas(request):
    rol_actual = request.user.perfil.rol.nombre.upper()

    # Si es CLIENTE, redirigir a su vista privada de 'mis_citas'
    if rol_actual == "CLIENTE":
        return redirect("agenda:mis_citas")

    # Si es ADMINISTRADOR, cargar todas las citas optimizando las relaciones
    citas = Citas.objects.all().select_related(
        'cliente',
        'manicurista',
        'servicios'
    ).order_by('-fecha', '-hora')

    contexto = {
        "datos": citas
    }
    return render(request, "cita/citas.html", contexto)




@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
def ver_todas_citas(request):
    try:
        # Ordenar las citas igual que en Citas asignadas.
        citas = (
            Citas.objects
            .select_related("cliente", "servicios")
            .annotate(
                orden_estado=Case(
                    When(estado="programada", then=Value(1)),
                    When(estado="en_proceso", then=Value(2)),
                    When(estado="completada", then=Value(3)),
                    When(estado="cancelada", then=Value(4)),
                    default=Value(5),
                    output_field=IntegerField(),
                )
            )
            .order_by("orden_estado", "fecha", "hora")
        )

        # Consultar las preferencias de recordatorios de cada cliente.
        for cita in citas:
            cita.recordatorios_whatsapp_activos = True

            if cita.cliente and cita.cliente.user:
                try:
                    preferencias_cliente = (
                        cita.cliente.user.preferencias_spa
                    )
                    cita.recordatorios_whatsapp_activos = (
                        preferencias_cliente.recordatorios_whatsapp
                    )
                except PreferenciasUsuario.DoesNotExist:
                    pass

        # Preferencias de fecha y hora del administrador.
        try:
            preferencias_accesibilidad = request.user.preferencias_spa
            formato_fecha = preferencias_accesibilidad.formato_fecha
            formato_hora = preferencias_accesibilidad.formato_hora
        except PreferenciasUsuario.DoesNotExist:
            formato_fecha = "DMY"
            formato_hora = "12"

    except DatabaseError:
        citas = []
        formato_fecha = "DMY"
        formato_hora = "12"

        messages.error(
            request,
            "Ocurrió un error en la base de datos al intentar cargar las citas."
        )

    except Exception:
        citas = []
        formato_fecha = "DMY"
        formato_hora = "12"

        messages.error(
            request,
            "Ocurrió un error inesperado al cargar las citas."
        )

    contexto = {
        "citas": citas,
        "formato_fecha": formato_fecha,
        "formato_hora": formato_hora,
    }

    return render(
        request,
        "administrador/todas_citas.html",
        contexto
    )



def calcular_descuento_cita(cliente, servicio, fecha_cita):
    """
    Retorna la promoción elegida y el importe descontado.
    Solo se aplica una promoción por cita.
    """

    descuentos = Descuentos.objects.filter(
        activo=True,
        fecha_inicio__lte=fecha_cita,
        fecha_fin__gte=fecha_cita
    )

    prioridad = {
        Descuentos.Tipo.CUMPLEAÑOS: 1,
        Descuentos.Tipo.PRIMERA_CITA: 2,
        Descuentos.Tipo.FECHA_ESPECIAL: 3,
        Descuentos.Tipo.TEMPORADA: 4,
        Descuentos.Tipo.PERSONALIZADO: 5,
    }

    descuentos = sorted(
        descuentos,
        key=lambda d: (prioridad.get(d.tipo, 99), d.fecha_fin)
    )

    for descuento in descuentos:

        # Validar cumpleaños: por ahora, solo el día exacto.
        if descuento.tipo == Descuentos.Tipo.CUMPLEAÑOS:
            nacimiento = cliente.fecha_nacimiento

            if not nacimiento:
                continue

            if (
                nacimiento.month != fecha_cita.month
                or nacimiento.day != fecha_cita.day
            ):
                continue

        # Validar que no haya tenido una cita completada
        # antes de la fecha de la nueva reserva.
        elif descuento.tipo == Descuentos.Tipo.PRIMERA_CITA:
            ya_tuvo_cita = Citas.objects.filter(
                cliente=cliente,
                estado="completada",
                fecha__lte=fecha_cita
            ).exists()

            ya_utilizo_promocion = Citas.objects.filter(
                cliente=cliente,
                descuento=descuento
            ).exclude(estado="cancelada").exists()

            if ya_tuvo_cita or ya_utilizo_promocion:
                continue

        # Calcular el valor del descuento.
        if descuento.tipo_beneficio == Descuentos.TipoBeneficio.PORCENTAJE:
            valor_descuento = int(
                (Decimal(servicio.precio) * descuento.valor / Decimal("100"))
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        else:
            valor_descuento = int(
                descuento.valor.quantize(
                    Decimal("1"),
                    rounding=ROUND_HALF_UP
                )
            )

        # El descuento nunca puede superar el precio.
        valor_descuento = min(valor_descuento, servicio.precio)

        if valor_descuento > 0:
            return descuento, valor_descuento

    return None, 0




def validar_uso_descuento(cliente, descuento, fecha_cita):
    """
    Devuelve un mensaje si la clienta no puede utilizar el descuento.
    Devuelve None si cumple las condiciones.
    """

    # 1. La promoción debe estar activa.
    if not descuento.activo:
        return "Esta promoción ya no está activa."

    # 2. La cita debe estar dentro de la vigencia.
    if not (
        descuento.fecha_inicio <= fecha_cita <= descuento.fecha_fin
    ):
        return "La fecha de la cita está fuera de la vigencia de la promoción."

    # 3. Consultar usos anteriores no cancelados.
    citas_con_descuento = Citas.objects.filter(
        cliente=cliente,
        descuento=descuento
    ).exclude(
        estado__iexact="cancelada"
    )

    # 4. Primera cita.
    if descuento.tipo == Descuentos.Tipo.PRIMERA_CITA:
        ya_completo_cita = Citas.objects.filter(
            cliente=cliente,
            estado__iexact="completada",
            fecha__lte=fecha_cita
        ).exists()

        if ya_completo_cita:
            return (
                "La promoción de primera cita es exclusiva para "
                "clientes que aún no han completado una cita."
            )

        if citas_con_descuento.exists():
            return "Ya tienes esta promoción reservada o utilizada."

    # 5. Cumpleaños: una vez por año calendario.
    elif descuento.tipo == Descuentos.Tipo.CUMPLEAÑOS:
        nacimiento = cliente.fecha_nacimiento

        if not nacimiento:
            return (
                "Registra tu fecha de nacimiento para utilizar "
                "esta promoción."
            )

        if (
            fecha_cita.month != nacimiento.month
            or fecha_cita.day != nacimiento.day
        ):
            return (
                "Esta promoción solo se puede utilizar "
                "el día de tu cumpleaños."
            )

        ya_utilizo_ese_anio = Citas.objects.filter(
            cliente=cliente,
            descuento__tipo=Descuentos.Tipo.CUMPLEAÑOS,
            fecha__year=fecha_cita.year
        ).exclude(
            estado__iexact="cancelada"
        ).exists()

        if ya_utilizo_ese_anio:
            return (
                "Ya tienes un descuento de cumpleaños reservado "
                "o utilizado durante ese año."
            )

    # 6. Temporada, fecha especial y personalizado.
    else:
        if citas_con_descuento.exists():
            return "Ya tienes esta promoción reservada o utilizada."

    return None




# CONSTANTES DE NEGOCIO
MAX_CITAS_DIARIAS_LOCAL = 50
MAX_CITAS_DIARIAS_MANICURISTA = 6  # Rango de 4 a 6 citas por día

@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
@require_http_methods(["GET", "POST"])
def crear_citas(request):
    cliente = get_object_or_404(Clientes, user=request.user)

    if request.method == "POST":
        try:
            manicurista_id = request.POST.get("manicurista")
            servicios_id = request.POST.get("servicios")
            fecha = request.POST.get("fecha")
            hora = request.POST.get("hora")

            # 1. Campos obligatorios
            if not manicurista_id or not servicios_id or not fecha or not hora:
                messages.error(request, "Todos los campos son obligatorios.")
                return redirect("agenda:crear_citas")

            # 2. Conversión de datos
            try:
                fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
                hora_obj = datetime.strptime(hora, "%H:%M").time()
            except ValueError:
                messages.error(request, "La fecha o la hora no tienen un formato válido.")
                return redirect("agenda:crear_citas")

            # 3. CONTROL 1: Bloqueo de fechas/horas pasadas
            ahora = datetime.now()
            inicio_nueva_cita = datetime.combine(fecha_obj, hora_obj)

            if inicio_nueva_cita < ahora:
                messages.error(request, "No puedes agendar citas en fechas u horas pasadas.")
                return redirect("agenda:crear_citas")

            if fecha_obj == date.today() and inicio_nueva_cita < (ahora + timedelta(hours=2)):
                messages.error(request, "Las citas para hoy deben agendarse con al menos 2 horas de anticipación.")
                return redirect("agenda:crear_citas")

            # 4. CONTROL 2: Validar rango de atención (8:00 AM a 6:00 PM)
            HORA_INICIO_JORNADA = time(8, 0)
            HORA_FIN_JORNADA = time(19, 0)

            if hora_obj < HORA_INICIO_JORNADA or hora_obj >= HORA_FIN_JORNADA:
                messages.error(request, "El horario de atención es de 8:00 AM a 6:00 PM.")
                return redirect("agenda:crear_citas")

            # Obtener Entidades
            manicurista = get_object_or_404(Manicurista, pk=manicurista_id, estado="Activa")
            servicio = get_object_or_404(Servicios, pk=servicios_id, estado="Activo")

            # 5. CONTROL 3: Duración del servicio y hora de finalización
            duracion_horas = getattr(servicio, 'duracion_horas', 1)
            fin_nueva_cita = inicio_nueva_cita + timedelta(hours=duracion_horas)

            limite_cierre = datetime.combine(fecha_obj, HORA_FIN_JORNADA)
            if fin_nueva_cita > limite_cierre:
                messages.error(
                    request,
                    f"El servicio dura {duracion_horas} hora(s) y supera la hora de cierre (6:00 PM)."
                )
                return redirect("agenda:crear_citas")

            # --- TRANSACCIÓN Y EVALUACIÓN DE CAPACIDADES ---
            with transaction.atomic():
                # Bloquear lecturas concurrentes para evaluar la capacidad de forma real
                citas_del_dia = Citas.objects.select_for_update().filter(
                    fecha=fecha_obj
                ).exclude(
                    estado__iexact="cancelada"
                )

                # 6. CONTROL 4: Capacidad Máxima Global del Spa
                if citas_del_dia.count() >= MAX_CITAS_DIARIAS_LOCAL:
                    messages.error(
                        request,
                        f"Lo sentimos, el Spa ha alcanzado el límite máximo de {MAX_CITAS_DIARIAS_LOCAL} "
                        f"citas para el día {fecha_obj.strftime('%d/%m/%Y')}. Elige otra fecha."
                    )
                    return redirect("agenda:crear_citas")

                # 7. CONTROL 5: Capacidad Máxima por Manicurista (4 a 6 citas/día)
                citas_manicurista = citas_del_dia.filter(manicurista=manicurista)
                if citas_manicurista.count() >= MAX_CITAS_DIARIAS_MANICURISTA:
                    messages.error(
                        request,
                        f"La manicurista {manicurista.nombre} ya completó su cupo máximo de "
                        f"{MAX_CITAS_DIARIAS_MANICURISTA} citas para este día. Elige otra manicurista o fecha."
                    )
                    return redirect("agenda:crear_citas")

                # 8. CONTROL 6: Prevenir que el cliente tenga dos citas solapadas el mismo día
                cita_cliente_existente = citas_del_dia.filter(cliente=cliente).exists()
                if cita_cliente_existente:
                    for c in citas_del_dia.filter(cliente=cliente):
                        dur = getattr(c.servicios, 'duracion_horas', 1)
                        i_ex = datetime.combine(c.fecha, c.hora)
                        f_ex = i_ex + timedelta(hours=dur)
                        if inicio_nueva_cita < f_ex and fin_nueva_cita > i_ex:
                            messages.error(request, "Ya tienes una cita agendada que se cruza con este horario.")
                            return redirect("agenda:crear_citas")

                # 9. CONTROL 7: Detección de solapamiento de agenda para la manicurista
                for cita_existente in citas_manicurista:
                    duracion_existente = getattr(cita_existente.servicios, 'duracion_horas', 1)
                    inicio_existente = datetime.combine(cita_existente.fecha, cita_existente.hora)
                    fin_existente = inicio_existente + timedelta(hours=duracion_existente)

                    if inicio_nueva_cita < fin_existente and fin_nueva_cita > inicio_existente:
                        messages.error(
                            request,
                            f"La manicurista {manicurista.nombre} ya tiene una cita ocupada entre las "
                            f"{inicio_existente.strftime('%I:%M %p')} y las {fin_existente.strftime('%I:%M %p')}."
                        )
                        return redirect("agenda:crear_citas")



                # 10. Aplicar el descuento pendiente, si existe.
                precio_original = servicio.precio
                descuento = None
                valor_descuento = 0

                descuento_pendiente_id = request.session.get(
                    "descuento_pendiente_id"
                )

                if descuento_pendiente_id:
                    descuento = Descuentos.objects.filter(
                        pk=descuento_pendiente_id,
                        activo=True,
                        fecha_inicio__lte=fecha_obj,
                        fecha_fin__gte=fecha_obj
                    ).first()




                    if not descuento:
                        request.session.pop("descuento_pendiente_id", None)
                        request.session.modified = True

                        messages.error(
                            request,
                            "La promoción ya no está disponible para la fecha seleccionada. "
                            "Elige otra promoción vigente."
                        )
                        return redirect("agenda:crear_citas")



                    # Validar todas las reglas de la promoción.
                    error_descuento = validar_uso_descuento(
                        cliente,
                        descuento,
                        fecha_obj
                    )

                    if error_descuento:
                        request.session.pop("descuento_pendiente_id", None)
                        request.session.modified = True

                        messages.error(request, error_descuento)
                        return redirect("agenda:crear_citas")



                    # Calcular el valor del descuento.
                    from decimal import Decimal, ROUND_HALF_UP

                    precio_decimal = Decimal(str(precio_original))

                    if descuento.tipo_beneficio == Descuentos.TipoBeneficio.PORCENTAJE:
                        valor_descuento = int(
                            (
                                precio_decimal * descuento.valor
                                / Decimal("100")
                            ).quantize(
                                Decimal("1"),
                                rounding=ROUND_HALF_UP
                            )
                        )
                    else:
                        valor_descuento = int(
                            descuento.valor.quantize(
                                Decimal("1"),
                                rounding=ROUND_HALF_UP
                            )
                        )

                    valor_descuento = min(
                        valor_descuento,
                        int(precio_original)
                    )

                    if valor_descuento <= 0:
                        messages.error(
                            request,
                            "No se pudo calcular un descuento válido."
                        )
                        return redirect("agenda:crear_citas")

                # Guardar la cita con el descuento calculado.
                cita = Citas.objects.create(
                    cliente=cliente,
                    manicurista=manicurista,
                    servicios=servicio,
                    fecha=fecha_obj,
                    hora=hora_obj,
                    precio_original=precio_original,
                    descuento_aplicado=valor_descuento,
                    descuento=descuento,
                    total=int(precio_original) - valor_descuento,
                    estado="programada"
                )

                notificar_cita_agendada(cita)

                # Limpiar la promoción pendiente después de guardar la cita.
                if descuento_pendiente_id:
                    request.session.pop("descuento_pendiente_id", None)
                    request.session.modified = True




            messages.success(request, "Cita agendada correctamente.")
            return redirect("agenda:mis_citas")

        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Error inesperado al agendar la cita"
            )

            messages.error(
                request,
                "Ocurrió un problema al agendar la cita. Inténtalo de nuevo."
            )
            return redirect("agenda:crear_citas")


    # GET
    manicurista = Manicurista.objects.filter(estado="Activa")
    servicios = Servicios.objects.filter(estado__iexact="Activo")

    descuento_pendiente = None
    descuento_pendiente_id = request.session.get(
        "descuento_pendiente_id"
    )

    if descuento_pendiente_id:
        descuento_pendiente = Descuentos.objects.filter(
            pk=descuento_pendiente_id,
            activo=True
        ).first()

        if not descuento_pendiente:
            request.session.pop("descuento_pendiente_id", None)

    # Obtener las preferencias de fecha y hora del usuario
    try:
        preferencias = request.user.preferencias_spa
        formato_fecha = preferencias.formato_fecha
        formato_hora = preferencias.formato_hora
    except PreferenciasUsuario.DoesNotExist:
        formato_fecha = "DMY"
        formato_hora = "12"

    return render(request, "cliente/crear_cita.html", {
        "cliente": cliente,
        "manicurista": manicurista,
        "servicios": servicios,
        "descuento_pendiente": descuento_pendiente,
        "formato_fecha": formato_fecha,
        "formato_hora": formato_hora,
    })





@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE", "ADMINISTRADOR")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def eliminar_citas(request, id):
    es_admin = (
        request.user.perfil.rol.nombre.upper() == "ADMINISTRADOR"
    )

    try:
        # Obtener la cita según el rol
        if es_admin:
            cita = get_object_or_404(Citas, pk=id)
        else:
            cliente = get_object_or_404(
                Clientes,
                user=request.user
            )
            cita = get_object_or_404(
                Citas,
                pk=id,
                cliente=cliente
            )

        # Normalizar el estado actual
        estado_actual = cita.estado.strip().lower()

        if estado_actual == "cancelada":
            messages.warning(
                request,
                "Esta cita ya se encuentra cancelada."
            )

        elif estado_actual == "completada":
            messages.error(
                request,
                "No puedes cancelar una cita que ya ha sido completada."
            )

        else:
            # Cancelar la cita sin eliminarla de la base de datos
            cita.estado = "cancelada"
            cita.save(update_fields=["estado"])

            # Notificar al cliente, la manicurista y los administradores
            notificar_cita_cancelada(cita)

            messages.success(
                request,
                "La cita se ha cancelado correctamente y el horario ha sido liberado."
            )

    except Exception:
        messages.error(
            request,
            "Ocurrió un error inesperado al procesar la cancelación."
        )

    # Redirigir según el rol del usuario
    if es_admin:
        return redirect("agenda:ver_todas_citas")

    return redirect("agenda:mis_citas")


# CONSTANTES DE NEGOCIO
MAX_CITAS_DIARIAS_LOCAL = 50
MAX_CITAS_DIARIAS_MANICURISTA = 6

@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
@require_http_methods(["GET", "POST"])
def actualizar_citas(request, id):
    cliente = get_object_or_404(Clientes, user=request.user)

    # Buscar cita perteneciente estrictamente al cliente
    cita = get_object_or_404(Citas, pk=id, cliente=cliente)

    # CONTROL 1: No permitir modificar citas finalizadas o canceladas
    if cita.estado == "Cancelada":
        messages.error(request, "No puedes editar una cita que ha sido cancelada.")
        return redirect("agenda:mis_citas")

    if cita.estado == "Completada":
        messages.error(request, "No puedes editar una cita que ya fue completada.")
        return redirect("agenda:mis_citas")

    if request.method == "POST":
        try:
            manicurista_id = request.POST.get("manicurista")
            servicios_id = request.POST.get("servicios")
            fecha = request.POST.get("fecha")
            hora = request.POST.get("hora")

            # 1. Campos obligatorios
            if not manicurista_id or not servicios_id or not fecha or not hora:
                messages.error(request, "Todos los campos son obligatorios.")
                return redirect("agenda:actualizar_citas", id=id)

            # 2. Conversión de fecha y hora
            try:
                fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
                hora_obj = datetime.strptime(hora, "%H:%M").time()
            except ValueError:
                messages.error(request, "La fecha o la hora no tienen un formato válido.")
                return redirect("agenda:actualizar_citas", id=id)

            # 3. CONTROL 2: Bloqueo de fechas/horas pasadas y margen de 2 horas para hoy
            ahora = datetime.now()
            inicio_nueva_cita = datetime.combine(fecha_obj, hora_obj)

            if inicio_nueva_cita < ahora:
                messages.error(request, "No puedes reprogramar una cita a una fecha u hora pasada.")
                return redirect("agenda:actualizar_citas", id=id)

            if fecha_obj == date.today() and inicio_nueva_cita < (ahora + timedelta(hours=2)):
                messages.error(
                    request,
                    "Para citas de hoy, la reprogramación requiere al menos 2 horas de anticipación."
                )
                return redirect("agenda:actualizar_citas", id=id)

            # 4. CONTROL 3: Validar rango de atención (8:00 AM a 6:00 PM)
            HORA_INICIO_JORNADA = time(8, 0)
            HORA_FIN_JORNADA = time(18, 0)

            if hora_obj < HORA_INICIO_JORNADA or hora_obj >= HORA_FIN_JORNADA:
                messages.error(request, "El horario de atención es de 8:00 AM a 6:00 PM.")
                return redirect("agenda:actualizar_citas", id=id)

            # Obtener Entidades activas
            manicurista = get_object_or_404(Manicurista, pk=manicurista_id, estado="Activa")
            servicio = get_object_or_404(Servicios, pk=servicios_id, estado="Activo")

            # 5. CONTROL 4: Duración del servicio y hora de cierre
            duracion_horas = getattr(servicio, 'duracion_horas', 1)
            fin_nueva_cita = inicio_nueva_cita + timedelta(hours=duracion_horas)

            limite_cierre = datetime.combine(fecha_obj, HORA_FIN_JORNADA)
            if fin_nueva_cita > limite_cierre:
                messages.error(
                    request,
                    f"El servicio dura {duracion_horas} hora(s) y supera el cierre (6:00 PM). Elige un horario más temprano."
                )
                return redirect("agenda:actualizar_citas", id=id)

            # --- TRANSACCIÓN Y EVALUACIÓN DE CAPACIDADES ---
            with transaction.atomic():
                # Bloqueo de concurrencia excluyendo la cita actual que se está reprogramando
                citas_del_dia = Citas.objects.select_for_update().filter(
                    fecha=fecha_obj
                ).exclude(
                    pk=cita.id
                ).exclude(
                    estado="Cancelada"
                )

                # 6. CONTROL 5: Capacidad Máxima Global del Spa
                if citas_del_dia.count() >= MAX_CITAS_DIARIAS_LOCAL:
                    messages.error(
                        request,
                        f"El Spa ha alcanzado la capacidad máxima de {MAX_CITAS_DIARIAS_LOCAL} citas para el día {fecha_obj.strftime('%d/%m/%Y')}."
                    )
                    return redirect("agenda:actualizar_citas", id=id)

                # 7. CONTROL 6: Capacidad Máxima por Manicurista
                citas_manicurista = citas_del_dia.filter(manicurista=manicurista)
                if citas_manicurista.count() >= MAX_CITAS_DIARIAS_MANICURISTA:
                    messages.error(
                        request,
                        f"La manicurista {manicurista.nombre} ya tiene su cupo máximo de "
                        f"{MAX_CITAS_DIARIAS_MANICURISTA} citas asignado para este día."
                    )
                    return redirect("agenda:actualizar_citas", id=id)

                # 8. CONTROL 7: Prevenir solapamientos con otras citas del mismo cliente ese día
                for c in citas_del_dia.filter(cliente=cliente):
                    dur = getattr(c.servicios, 'duracion_horas', 1)
                    i_ex = datetime.combine(c.fecha, c.hora)
                    f_ex = i_ex + timedelta(hours=dur)
                    if inicio_nueva_cita < f_ex and fin_nueva_cita > i_ex:
                        messages.error(request, "Tienes otra cita agendada que se traslapa con este horario.")
                        return redirect("agenda:actualizar_citas", id=id)

                # 9. CONTROL 8: Detección de solapamiento de horario para la manicurista
                for cita_existente in citas_manicurista:
                    duracion_existente = getattr(cita_existente.servicios, 'duracion_horas', 1)
                    inicio_existente = datetime.combine(cita_existente.fecha, cita_existente.hora)
                    fin_existente = inicio_existente + timedelta(hours=duracion_existente)

                    if inicio_nueva_cita < fin_existente and fin_nueva_cita > inicio_existente:
                        messages.error(
                            request,
                            f"La manicurista {manicurista.nombre} ya tiene una cita ocupada entre las "
                            f"{inicio_existente.strftime('%I:%M %p')} y las {fin_existente.strftime('%I:%M %p')}."
                        )
                        return redirect("agenda:actualizar_citas", id=id)

                # 10. Actualización atómica de la Cita
                cita.manicurista = manicurista
                cita.servicios = servicio
                cita.fecha = fecha_obj
                cita.hora = hora_obj
                cita.total = servicio.precio
                cita.save()
                notificar_cita_modificada(cita)

            messages.success(request, "Cita actualizada correctamente.")
            return redirect("agenda:mis_citas")

        except Exception:
            messages.error(request, "Ocurrió un error inesperado al actualizar la cita.")
            return redirect("agenda:actualizar_citas", id=id)

    # PETICIÓN GET
    manicurista = Manicurista.objects.filter(estado="Activa")
    servicios = Servicios.objects.filter(estado="Activo")

    # Obtener las preferencias de fecha y hora del usuario
    try:
        preferencias = request.user.preferencias_spa
        formato_fecha = preferencias.formato_fecha
        formato_hora = preferencias.formato_hora
    except PreferenciasUsuario.DoesNotExist:
        formato_fecha = "DMY"
        formato_hora = "12"

    contexto = {
        "cita": cita,
        "cliente": cliente,
        "manicurista": manicurista,
        "servicios": servicios,
        "formato_fecha": formato_fecha,
        "formato_hora": formato_hora,
    }

    return render(request, "cliente/actualizar_citas.html", contexto)

import re
from datetime import datetime, date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction, IntegrityError
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password

# Importaciones locales
from .models import Manicurista, Rol, PerfilUsuario, Citas
from .utils import validar_password


# 1. LISTAR MANICURISTAS
@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
def ver_manicuristas(request):
    try:
        manicuristas = Manicurista.objects.all().select_related("user")

        contexto = {
            "datos": manicuristas,
            "es_admin": True
        }

        return render(request, "administrador/manicuristas.html", contexto)

    except Exception as e:
        # Imprime la traza exacta en la terminal/consola de Django
        print(f"--- ERROR EXACTO EN VER_MANICURISTAS: {type(e).__name__} -> {e} ---")

        messages.error(
            request,
            f"Ocurrió un error al cargar el catálogo: {e}"  # Muestra el error en pantalla temporalmente
        )
        return redirect("agenda:dashboard")

# CATÁLOGO DE MANICURISTAS PARA CLIENTES
@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
def manicuristas_cliente(request):
    try:
        manicuristas = (
            Manicurista.objects
            .filter(estado="Activa")
            .select_related("user")
            .prefetch_related(
                Prefetch(
                    "portafolio",
                    queryset=PortafolioManicurista.objects.filter(visible=True)
                )
            )
        )

        contexto = {
            "manicuristas": manicuristas,
        }

        return render(
            request,
            "cliente/manicuristas.html",
            contexto
        )

    except Exception as e:
        print(
            f"--- ERROR EXACTO EN MANICURISTAS_CLIENTE: "
            f"{type(e).__name__} -> {e} ---"
        )

        messages.error(
            request,
            "Ocurrió un error al cargar las manicuristas."
        )

        return redirect("agenda:dashboard")

@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
def portafolio_manicurista_cliente(request, manicurista_id):

    try:
        manicurista = get_object_or_404(
            Manicurista,
            id=manicurista_id,
            estado="Activa"
        )

        trabajos = PortafolioManicurista.objects.filter(
            manicurista=manicurista,
            visible=True
        ).order_by("-fecha_publicacion")

        contexto = {
            "manicurista": manicurista,
            "trabajos": trabajos,
        }

        return render(
            request,
            "cliente/portafolio_manicurista_cliente.html",
            contexto
        )

    except Exception as e:
        print(
            f"--- ERROR EXACTO EN PORTAFOLIO_MANICURISTA_CLIENTE: "
            f"{type(e).__name__} -> {e} ---"
        )

        messages.error(
            request,
            "Ocurrió un error al cargar el portafolio."
        )

        return redirect("agenda:manicuristas_cliente")



@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_http_methods(["GET", "POST"])
def crear_manicurista(request):
    if request.method == "POST":
        password = request.POST.get("password", "")
        email = request.POST.get("email", "").strip().lower()
        nombre = request.POST.get("nombre", "").strip()
        apellido = request.POST.get("apellido", "").strip()
        telefono = request.POST.get("telefono", "").strip()
        especialidad = request.POST.get("especialidad", "").strip()
        fecha_ingreso_raw = request.POST.get("fecha_ingreso", "").strip()
        foto_perfil = request.FILES.get("foto_perfil")

        form_data = {
            "nombre": nombre,
            "apellido": apellido,
            "email": email,
            "telefono": telefono,
            "especialidad": especialidad,
            "fecha_ingreso": fecha_ingreso_raw,
        }

        def mostrar_error(mensaje):
            messages.error(request, mensaje)
            return render(
                request,
                "manicurista/crear_manicurista.html",
                {"form_data": form_data},
            )

        # 1. Validar campos obligatorios.
        if not all([
            nombre,
            apellido,
            email,
            password,
            telefono,
            especialidad,
            fecha_ingreso_raw,
        ]):
            return mostrar_error(
                "Todos los campos obligatorios deben diligenciarse."
            )

        # 2. Validar la contraseña.
        error_pass = validar_password(password)

        if error_pass:
            return mostrar_error(error_pass)

        # 3. Validar el formato del correo.
        try:
            validate_email(email)
        except ValidationError:
            return mostrar_error(
                "El correo electrónico no tiene un formato válido."
            )

        # 4. Comprobar que el correo no esté registrado.
        if (
            User.objects.filter(email__iexact=email).exists()
            or User.objects.filter(username__iexact=email).exists()
        ):
            return mostrar_error(
                "Ya existe un usuario registrado con ese correo."
            )

        # 5. Validar el teléfono.
        # Se permiten espacios, paréntesis, guiones y el signo +.
        digitos_telefono = re.sub(r"\D", "", telefono)

        if (
            not re.fullmatch(r"[+\d\s().-]+", telefono)
            or not 7 <= len(digitos_telefono) <= 15
        ):
            return mostrar_error(
                "El número de teléfono ingresado no es válido."
            )

        # 6. Validar la fecha en formato día/mes/año.
        try:
            fecha_ingreso = datetime.strptime(
                fecha_ingreso_raw,
                "%d/%m/%Y",
            ).date()

            # Evitar fechas escritas de manera ambigua o incorrecta.
            if fecha_ingreso.strftime("%d/%m/%Y") != fecha_ingreso_raw:
                raise ValueError

            if fecha_ingreso > date.today():
                return mostrar_error(
                    "La fecha de ingreso no puede ser una fecha futura."
                )

        except ValueError:
            return mostrar_error(
                "Ingresa una fecha válida con el formato dd/mm/aaaa. "
                "Por ejemplo: 05/03/2026."
            )

        # 7. Verificar el correo con el servicio externo.
        api_key = os.environ.get("EMAIL_VALIDATION_API_KEY")

        if not api_key:
            return mostrar_error(
                "La validación externa del correo no está configurada. "
                "Contacta al administrador del sistema."
            )

        try:
            respuesta = requests.post(
                "https://api.email-validation.org/v1/validate",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "email": email,
                    "timeout": 6,
                },
                timeout=10,
            )

            respuesta.raise_for_status()
            resultado = respuesta.json()
            estado_correo = str(
                resultado.get("status", "")
            ).strip().lower()

        except requests.RequestException:
            return mostrar_error(
                "No fue posible verificar el correo en este momento. "
                "Inténtalo nuevamente más tarde."
            )

        except ValueError:
            return mostrar_error(
                "El servicio de validación devolvió una respuesta no válida."
            )

        # Aceptar únicamente el estado valid.
        if estado_correo != "valid":
            if estado_correo == "invalid":
                mensaje = (
                    "El correo no parece existir o no puede recibir mensajes. "
                    "Verifica la dirección ingresada."
                )
            elif estado_correo == "catch_all":
                mensaje = (
                    "No se pudo confirmar que el buzón exista. "
                    "Utiliza un correo que pueda verificarse."
                )
            else:
                mensaje = (
                    "No fue posible confirmar que el correo sea válido. "
                    "Verifica la dirección e inténtalo nuevamente."
                )

            return mostrar_error(mensaje)

        # 8. Crear usuario, perfil y manicurista en una transacción.
        try:
            with transaction.atomic():
                rol, _ = Rol.objects.get_or_create(
                    nombre="MANICURISTA"
                )

                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=nombre,
                    last_name=apellido,
                )

                # Si una señal ya creó el perfil, actualizarlo.
                perfil, _ = PerfilUsuario.objects.get_or_create(
                    user=user
                )
                perfil.rol = rol
                perfil.save()

                Manicurista.objects.create(
                    user=user,
                    nombre=nombre,
                    apellido=apellido,
                    telefono=telefono,
                    email=email,
                    password=make_password(password),
                    especialidad=especialidad,
                    fecha_ingreso=fecha_ingreso,
                    estado="Activa",
                    foto_perfil=foto_perfil,
                )

            messages.success(
                request,
                f"Manicurista '{nombre} {apellido}' registrada correctamente.",
            )
            return redirect("agenda:ver_manicuristas")

        except IntegrityError:
            return mostrar_error(
                "Ocurrió un conflicto al guardar la manicurista. "
                "Verifica que el correo no esté registrado."
            )

        except Exception:
            # Registrar el detalle en los logs del servidor.
            import logging
            logging.getLogger(__name__).exception(
                "Error inesperado al crear una manicurista."
            )
            return mostrar_error(
                "Ocurrió un error inesperado al crear la manicurista."
            )

    return render(
        request,
        "manicurista/crear_manicurista.html",
        {"form_data": {}},
    )


# 3. ELIMINAR / DESACTIVAR MANICURISTA
@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_POST
def eliminar_manicurista(request, id):
    try:
        manicurista = get_object_or_404(Manicurista, pk=id)

        if manicurista.estado == "Inactiva":
            messages.warning(request, f"La manicurista '{manicurista.nombre}' ya se encuentra inactiva.")
            return redirect("agenda:ver_manicuristas")

        ahora = datetime.now()

        tiene_citas_pendientes = Citas.objects.filter(
            manicurista=manicurista,
            fecha__gte=ahora.date()
        ).exclude(
            estado__iexact="cancelada"
        ).exclude(
            estado__iexact="completada"
        ).exists()

        if tiene_citas_pendientes:
            messages.error(
                request,
                f"No se puede inactivar a '{manicurista.nombre}' porque tiene citas pendientes o programadas. "
                "Reasigna o cancela sus citas antes de proceder."
            )
            return redirect("agenda:ver_manicuristas")

        with transaction.atomic():
            manicurista.estado = "Inactiva"
            manicurista.save()

            if manicurista.user:
                manicurista.user.is_active = False
                manicurista.user.save()

        messages.success(request, f"La manicurista '{manicurista.nombre}' ha sido desactivada correctamente.")

    except Exception as e:
        print(f"Error al eliminar manicurista: {e}")
        messages.error(request, "Ocurrió un error inesperado al intentar desactivar la manicurista.")

    return redirect("agenda:ver_manicuristas")


# 4. ACTUALIZAR MANICURISTA
@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_http_methods(["GET", "POST"])
def actualizar_manicurista(request, id):
    manicurista = get_object_or_404(Manicurista, pk=id)

    if request.method == "POST":
        nombre = request.POST.get("nombre", "").strip()
        apellido = request.POST.get("apellido", "").strip()
        telefono = request.POST.get("telefono", "").strip()
        email = request.POST.get("email", "").strip().lower()
        especialidad = request.POST.get("especialidad", "").strip()
        fecha_ingreso_raw = request.POST.get("fecha_ingreso")
        estado = request.POST.get("estado", "").strip()
        foto_perfil = request.FILES.get("foto_perfil")

        if not all([nombre, apellido, telefono, email, especialidad, fecha_ingreso_raw, estado]):
            messages.error(request, "Todos los campos son obligatorios.")
            return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})

        patron_email = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(patron_email, email):
            messages.error(request, "El correo electrónico no tiene un formato válido.")
            return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})

        if manicurista.user:
            correo_ocupado = User.objects.filter(email__iexact=email).exclude(pk=manicurista.user.id).exists()
        else:
            correo_ocupado = User.objects.filter(email__iexact=email).exists()

        if correo_ocupado:
            messages.error(request, "El correo electrónico ya está registrado por otro usuario.")
            return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})

        if not re.match(r"^\+?\d{7,15}$", telefono):
            messages.error(request, "El número de teléfono ingresado no es válido.")
            return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})

        try:
            fecha_ingreso = datetime.strptime(fecha_ingreso_raw, "%Y-%m-%d").date()
            if fecha_ingreso > date.today():
                messages.error(request, "La fecha de ingreso no puede ser una fecha futura.")
                return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})
        except ValueError:
            messages.error(request, "La fecha de ingreso no tiene un formato válido.")
            return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})

        ESTADOS_PERMITIDOS = ["Activa", "Inactiva"]
        if estado not in ESTADOS_PERMITIDOS:
            messages.error(request, "El estado seleccionado no es válido.")
            return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})

        if estado == "Inactiva" and manicurista.estado == "Activa":
            ahora = datetime.now()
            tiene_citas_futuras = Citas.objects.filter(
                manicurista=manicurista,
                fecha__gte=ahora.date()
            ).exclude(
                estado__in=["Cancelada", "Completada"]
            ).exists()

            if tiene_citas_futuras:
                messages.error(
                    request,
                    f"No se puede cambiar el estado a 'Inactiva' porque {manicurista.nombre} tiene citas "
                    "programadas pendientes. Cancélalas o reasígnalas antes de desactivarla."
                )
                return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})

        try:
            with transaction.atomic():
                manicurista.nombre = nombre
                manicurista.apellido = apellido
                manicurista.telefono = telefono
                manicurista.email = email
                manicurista.especialidad = especialidad
                manicurista.fecha_ingreso = fecha_ingreso
                manicurista.estado = estado
                if foto_perfil:
                    manicurista.foto_perfil = foto_perfil
                manicurista.save()

                if manicurista.user:
                    usuario = manicurista.user
                    usuario.first_name = nombre
                    usuario.last_name = apellido
                    usuario.email = email
                    usuario.username = email
                    usuario.is_active = (estado == "Activa")
                    usuario.save()

            messages.success(request, f"Manicurista '{nombre}' actualizada correctamente.")
            return redirect("agenda:ver_manicuristas")

        except IntegrityError:
            messages.error(request, "Ocurrió un conflicto de integridad de datos al actualizar.")
        except Exception as e:
            print(f"Error al actualizar manicurista: {e}")
            messages.error(request, "Ocurrió un error inesperado al actualizar la manicurista.")

        return render(request, "manicurista/formulario_manicuristas.html", {"datos": manicurista})

    contexto = {
        "datos": manicurista
    }
    return render(request, "manicurista/formulario_manicuristas.html", contexto)


@login_required(login_url="agenda:login")
@require_http_methods(["GET", "POST"])
@requiere_rol("MANICURISTA")
def cambiar_estado_cita(request, cita_id, nuevo_estado):

    try:
        manicurista_actual = Manicurista.objects.get(
            user=request.user
        )
    except Manicurista.DoesNotExist:
        messages.error(
            request,
            "No se encontró un perfil de manicurista asociado a tu usuario."
        )
        return redirect("agenda:citas_asignadas")

    cita = get_object_or_404(
        Citas,
        id=cita_id,
        manicurista=manicurista_actual
    )

    # Validar el estado normalizado
    nuevo_estado = nuevo_estado.strip().lower()
    estados_validos = dict(Citas.ESTADOS_CITA)

    if nuevo_estado not in estados_validos:
        messages.error(
            request,
            "El estado seleccionado no es válido."
        )
        return redirect("agenda:citas_asignadas")

    estado_anterior = cita.estado.strip().lower()

    if estado_anterior == nuevo_estado:
        messages.warning(
            request,
            f"La cita ya se encuentra en estado '{estados_validos[nuevo_estado]}'."
        )
        return redirect("agenda:citas_asignadas")

    try:
        with transaction.atomic():
            cita.estado = nuevo_estado
            cita.save(update_fields=["estado"])

            # Notificar la cancelación
            if (
                estado_anterior != "cancelada"
                and nuevo_estado == "cancelada"
            ):
                notificar_cita_cancelada(cita)

            # Notificar cuando la cita se completa
            if (
                estado_anterior != "completada"
                and nuevo_estado == "completada"
            ):
                notificar_resena_pendiente(cita)
                crear_recibo_y_notificar(cita)

        messages.success(
            request,
            f"Estado actualizado exitosamente a '{estados_validos[nuevo_estado]}'."
        )

    except Exception as e:
        # Registrar el error para facilitar la depuración
        import logging
        logging.getLogger(__name__).exception(
            "Error al actualizar el estado de la cita %s", cita_id
        )
        messages.error(
            request,
            "Ocurrió un error interno al intentar actualizar el estado de la cita."
        )

    return redirect("agenda:citas_asignadas")


@require_POST  # Seguridad: Evita accesos por URL GET, garantizando que solo se ejecute mediante envío de formulario
@requiere_rol("MANICURISTA")
def registrar_pago_cita(request, cita_id):
    # Control de seguridad: Validar existencia del ID
    if not cita_id:
        messages.error(request, "Identificador de cita no válido.")
        return redirect('agenda:citas_asignadas')

    try:
        # Obtener la manicurista usando 'user=request.user' (coherente con el modelo)
        manicurista_actual = Manicurista.objects.get(user=request.user)
    except Manicurista.DoesNotExist:
        messages.error(request, "No se encontró un perfil de manicurista asociado a tu usuario.")
        return redirect('agenda:citas_asignadas')

    # Seguridad: Obtener la cita validando que pertenezca estrictamente a la manicurista en sesión
    cita = get_object_or_404(Citas, id=cita_id, manicurista=manicurista_actual)

    try:
        # Robustez: Usar transacción atómica para proteger la creación o actualización del pago
        with transaction.atomic():
            pago, creado = Pagos.objects.get_or_create(
                citas=cita,
                defaults={
                    'valor': cita.total,
                    'estado': 'Realizado',
                    'metodo_pago': 'Efectivo'
                }
            )

            # Si ya existía, validamos si requiere actualización de estado
            if not creado:
                if pago.estado == 'Realizado':
                    # Recuperar el recibo o la notificación si faltan
                    crear_recibo_y_notificar(cita)

                    messages.info(request, "El pago de esta cita ya se encontraba registrado como realizado.")
                    return redirect('agenda:citas_asignadas')

                pago.valor = cita.total
                pago.estado = 'Realizado'
                pago.save()

            # Crear el recibo y notificar al cliente si la cita está completada y el pago realizado
            crear_recibo_y_notificar(cita)

            messages.success(request, "Pago registrado correctamente.")

    except Exception as e:
        # Control de excepciones ante fallos de base de datos
        messages.error(request, "Ocurrió un error inesperado al procesar el registro del pago.")

    return redirect('agenda:citas_asignadas')


# ---------PORTAFOLIO MANICURISTA ----------------
@login_required(login_url="agenda:login")
@requiere_rol("MANICURISTA")
def mi_portafolio(request):
    try:
        manicurista = get_object_or_404(
            Manicurista,
            user=request.user
        )

        trabajos = PortafolioManicurista.objects.filter(
            manicurista=manicurista
        ).order_by("-fecha_publicacion")

        # Obtener el formato de fecha guardado en los ajustes del usuario
        try:
            formato_fecha = request.user.preferencias_spa.formato_fecha
        except PreferenciasUsuario.DoesNotExist:
            formato_fecha = "DMY"

        contexto = {
            "manicurista": manicurista,
            "trabajos": trabajos,
            "formato_fecha": formato_fecha,
        }

        return render(
            request,
            "manicurista/mi_portafolio.html",
            contexto
        )

    except Exception:
        messages.error(
            request,
            "Ocurrió un error al cargar tu portafolio."
        )
        return redirect("agenda:dashboard")

@login_required(login_url="agenda:login")
@requiere_rol("MANICURISTA")
@require_http_methods(["GET", "POST"])
def agregar_trabajo_portafolio(request):

    manicurista = get_object_or_404(
        Manicurista,
        user=request.user
    )

    if request.method == "POST":
        try:
            titulo = request.POST.get("titulo", "").strip()
            descripcion = request.POST.get("descripcion", "").strip()
            categoria = request.POST.get("categoria", "").strip()
            imagen = request.FILES.get("imagen")

            if not titulo:
                messages.error(
                    request,
                    "El título del trabajo es obligatorio."
                )
                return redirect(
                    "agenda:agregar_trabajo_portafolio"
                )

            if not imagen:
                messages.error(
                    request,
                    "Debes seleccionar una imagen."
                )
                return redirect(
                    "agenda:agregar_trabajo_portafolio"
                )

            trabajo = PortafolioManicurista(
                manicurista=manicurista,
                titulo=titulo,
                descripcion=descripcion,
                categoria=categoria,
                imagen=imagen,
                visible=True
            )

            trabajo.full_clean()
            trabajo.save()

            messages.success(
                request,
                "El trabajo se agregó correctamente."
            )

            return redirect(
                "agenda:mi_portafolio"
            )

        except ValidationError as e:

            messages.error(
                request,
                e.messages[0]
            )

            return redirect(
                "agenda:agregar_trabajo_portafolio"
            )

        except Exception:

            messages.error(
                request,
                "Ocurrió un error al guardar el trabajo."
            )

            return redirect(
                "agenda:agregar_trabajo_portafolio"
            )

    return render(
        request,
        "manicurista/agregar_trabajo_portafolio.html",
        {
            "manicurista": manicurista
        }
    )

@login_required(login_url="agenda:login")
@requiere_rol("MANICURISTA")
@require_http_methods(["POST"])
def cambiar_visibilidad_portafolio(request, id):

    manicurista = get_object_or_404(
        Manicurista,
        user=request.user
    )

    trabajo = get_object_or_404(
        PortafolioManicurista,
        id=id,
        manicurista=manicurista
    )

    try:
        trabajo.visible = not trabajo.visible
        trabajo.save(update_fields=["visible"])

        if trabajo.visible:
            messages.success(
                request,
                "El trabajo ahora es visible para los clientes."
            )
        else:
            messages.success(
                request,
                "El trabajo se ocultó para los clientes."
            )

    except Exception:
        messages.error(
            request,
            "No fue posible cambiar la visibilidad del trabajo."
        )

    return redirect("agenda:mi_portafolio")

@login_required(login_url="agenda:login")
@requiere_rol("MANICURISTA")
@require_http_methods(["GET", "POST"])
def editar_trabajo_portafolio(request, id):

    manicurista = get_object_or_404(
        Manicurista,
        user=request.user
    )

    trabajo = get_object_or_404(
        PortafolioManicurista,
        id=id,
        manicurista=manicurista
    )

    if request.method == "POST":
        try:
            titulo = request.POST.get("titulo", "").strip()
            descripcion = request.POST.get("descripcion", "").strip()
            categoria = request.POST.get("categoria", "").strip()
            imagen = request.FILES.get("imagen")

            if not titulo:
                messages.error(
                    request,
                    "El título del trabajo es obligatorio."
                )

                return redirect(
                    "agenda:editar_trabajo_portafolio",
                    id=id
                )

            trabajo.titulo = titulo
            trabajo.descripcion = descripcion
            trabajo.categoria = categoria

            if imagen:
                trabajo.imagen = imagen

            trabajo.full_clean()
            trabajo.save()

            messages.success(
                request,
                "El trabajo se actualizó correctamente."
            )

            return redirect(
                "agenda:mi_portafolio"
            )

        except ValidationError as e:

            messages.error(
                request,
                e.messages[0]
            )

            return redirect(
                "agenda:editar_trabajo_portafolio",
                id=id
            )

        except Exception:

            messages.error(
                request,
                "Ocurrió un error al actualizar el trabajo."
            )

    return render(
        request,
        "manicurista/editar_trabajo_portafolio.html",
        {
            "trabajo": trabajo,
            "manicurista": manicurista
        }
    )

@login_required(login_url="agenda:login")
@requiere_rol("MANICURISTA")
@require_http_methods(["POST"])
def eliminar_trabajo_portafolio(request, id):

    manicurista = get_object_or_404(
        Manicurista,
        user=request.user
    )

    trabajo = get_object_or_404(
        PortafolioManicurista,
        id=id,
        manicurista=manicurista
    )

    try:
        trabajo.delete()

        messages.success(
            request,
            "El trabajo se eliminó correctamente."
        )

    except Exception:
        messages.error(
            request,
            "No fue posible eliminar el trabajo."
        )

    return redirect("agenda:mi_portafolio")

#################################################################


@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_POST
@transaction.atomic
def cambiar_estado_cita_admin(request, cita_id, nuevo_estado):

    cita = get_object_or_404(Citas, id=cita_id)

    # Normalizar el estado recibido
    nuevo_estado = nuevo_estado.strip().lower()
    estados_validos = dict(Citas.ESTADOS_CITA)

    # Validar el estado
    if nuevo_estado not in estados_validos:
        messages.error(
            request,
            f"El estado seleccionado '{nuevo_estado}' no es válido."
        )
        return redirect("agenda:ver_todas_citas")

    estado_anterior = cita.estado.strip().lower()

    # Evitar actualizar el mismo estado
    if estado_anterior == nuevo_estado:
        messages.warning(
            request,
            f"La cita ya se encuentra en estado '{estados_validos[nuevo_estado]}'."
        )
        return redirect("agenda:ver_todas_citas")

    try:
        with transaction.atomic():
            # Actualizar la cita
            cita.estado = nuevo_estado
            cita.save(update_fields=["estado"])

            # Notificar cuando se cancela la cita
            if (
                estado_anterior != "cancelada"
                and nuevo_estado == "cancelada"
            ):
                notificar_cita_cancelada(cita)

            # Notificar cuando se completa la cita
            if (
                estado_anterior != "completada"
                and nuevo_estado == "completada"
            ):
                notificar_resena_pendiente(cita)
                crear_recibo_y_notificar(cita)

        messages.success(
            request,
            f"Estado actualizado correctamente a '{estados_validos[nuevo_estado]}'."
        )

    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Error al actualizar el estado de la cita %s",
            cita_id
        )

        messages.error(
            request,
            "Ocurrió un error interno al intentar actualizar el estado de la cita."
        )

    return redirect("agenda:ver_todas_citas")




@require_POST # Seguridad nativa: Rechaza cualquier acceso por GET directamente a nivel de decorador
@requiere_rol("ADMINISTRADOR")
def registrar_pago_admin(request, cita_id):
    if not cita_id:
        messages.error(request, "Identificador de cita no válido.")
        return redirect("agenda:ver_todas_citas")

    cita = get_object_or_404(Citas, id=cita_id)

    metodo_seleccionado = request.POST.get(
        "metodo_pago", "Efectivo"
    ).strip()

    if not metodo_seleccionado:
        metodo_seleccionado = "Efectivo"

    try:
        with transaction.atomic():
            pago, creado = Pagos.objects.get_or_create(
                citas=cita,
                defaults={
                    "valor": cita.total,
                    "estado": "Realizado",
                    "metodo_pago": metodo_seleccionado,
                },
            )

            if not creado:
                if (
                    pago.estado == "Realizado"
                    and pago.metodo_pago == metodo_seleccionado
                ):
                    crear_recibo_y_notificar(cita)

                    messages.info(
                        request,
                        "El pago de esta cita ya se encontraba "
                        "registrado con los mismos datos."
                    )
                    return redirect("agenda:ver_todas_citas")

                pago.valor = cita.total
                pago.estado = "Realizado"
                pago.metodo_pago = metodo_seleccionado
                pago.save()

            # Se ejecuta tanto para pagos nuevos como actualizados.
            # El helper debe verificar que la cita esté completada
            # y que el pago esté realizado antes de crear el recibo.
            crear_recibo_y_notificar(cita)

            messages.success(
                request,
                f"Pago registrado correctamente por "
                f"{metodo_seleccionado}."
            )

    except Exception:
        messages.error(
            request,
            "Ocurrió un error interno al intentar registrar "
            "el pago de la cita."
        )

    return redirect("agenda:ver_todas_citas")



def validar_imagen_servicio(imagen):
    if not imagen:
        return

    if imagen.size > 5 * 1024 * 1024:
        raise ValueError("La imagen no puede superar los 5 MB.")

    try:
        imagen.seek(0)

        with Image.open(imagen) as archivo:
            if archivo.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError(
                    "Usa una imagen JPG, PNG o WebP."
                )

            archivo.verify()

        imagen.seek(0)

    except (UnidentifiedImageError, OSError):
        raise ValueError(
            "El archivo seleccionado no es una imagen válida."
        )


#CRUD SERVICIOS

from django.db import DatabaseError
# CRUD SERVICIOS: CONSULTAR

# Solo permite solicitudes GET, utilizadas para consultar información.
@require_http_methods(["GET"])

# Restringe el acceso a usuarios con el rol ADMINISTRADOR.
@requiere_rol("ADMINISTRADOR")
def ver_servicio(request):

    # Consulta todos los servicios almacenados en la base de datos.
    servicios = Servicios.objects.all().order_by("nombre")

    # Crea un diccionario con los datos que recibirá la plantilla HTML.
    # La clave "datos" permite acceder a los servicios desde el template.
    contexto = {
        "datos": servicios,
    }

    # Renderiza la plantilla y le entrega el contexto.
    # Django utilizará los registros para construir la lista de servicios.
    return render(
        request,
        "servicio/lista_servicios.html",
        contexto
    )

# CRUD SERVICIOS: CREAR

# Permite abrir el formulario mediante GET y procesarlo mediante POST.
@require_http_methods(["GET", "POST"])

# Solo un administrador puede crear servicios.
@requiere_rol("ADMINISTRADOR")
def crear_servicio(request):

    # Comprueba si el usuario envió el formulario.
    if request.method == "POST":

        # Obtiene los valores enviados desde los campos del formulario.
        # strip() elimina espacios al principio y al final del texto.
        nombre = request.POST.get("nombre", "").strip()
        precio = request.POST.get("precio", "").strip()
        descripcion = request.POST.get("descripcion", "").strip()
        duracion = request.POST.get("duracion", "").strip()

        # Obtiene la fotografía enviada desde el formulario.
        imagen = request.FILES.get("imagen")

        # Si el formulario no envía la comisión, utiliza 50 %.
        porcentaje_comision = request.POST.get(
            "porcentaje_comision", "50"
        ).strip()

        # Si no se envía el estado, el servicio se crea como Activo.
        estado = request.POST.get("estado", "Activo").strip()

        # Verifica que los campos obligatorios tengan algún valor.
        # La descripción y la fotografía no son obligatorias.
        if not nombre or not precio or not duracion:
            messages.error(
                request,
                "Completa los campos obligatorios del servicio."
            )

            # Regresa a la lista sin guardar el servicio.
            return redirect("agenda:ver_servicio")

        # Comprueba que la fotografía sea válida, si se adjuntó alguna.
        try:
            validar_imagen_servicio(imagen)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("agenda:crear_servicio")

        try:
            # Los datos de un formulario llegan normalmente como texto.
            # int() los convierte a números enteros para almacenarlos.
            precio = int(precio)
            duracion = int(duracion)
            porcentaje_comision = int(porcentaje_comision)

            # El precio y la duración deben ser mayores que cero.
            if precio <= 0 or duracion <= 0:
                raise ValueError

            # La comisión debe estar entre 0 % y 100 %.
            if not 0 <= porcentaje_comision <= 100:
                raise ValueError

            # Comprueba que el estado enviado sea una opción válida
            # definida en Servicios.ESTADOS.
            if estado not in dict(Servicios.ESTADOS):
                raise ValueError

            # Abre una transacción para realizar la operación de forma segura.
            # Si ocurre un error de base de datos, la operación no se confirma.
            with transaction.atomic():

                # Crea el registro y lo guarda en la base de datos.
                servicio = Servicios.objects.create(
                    nombre=nombre,
                    precio=precio,
                    descripcion=descripcion,
                    duracion=duracion,
                    porcentaje_comision=porcentaje_comision,
                    estado=estado,
                    imagen=imagen,
                )

            # Informa al usuario que el servicio se creó correctamente.
            messages.success(
                request,
                f"Servicio '{servicio.nombre}' creado correctamente."
            )

        # Captura errores de conversión o de validación.
        # Por ejemplo: precio = "abc", duración = 0 o comisión = 150.
        except ValueError:
            messages.error(
                request,
                "Verifica el precio, la duración y la comisión. "
                "El precio y la duración deben ser mayores que cero "
                "y la comisión debe estar entre 0 y 100."
            )

        # Captura errores producidos por la base de datos.
        except DatabaseError:
            messages.error(
                request,
                "Ocurrió un error en la base de datos al guardar el servicio."
            )

        # Finaliza el procesamiento y vuelve a la lista de servicios.
        return redirect("agenda:ver_servicio")

    # Si la solicitud es GET, muestra el formulario vacío.
    return render(request, "servicio/formulario_servicio.html")


# CRUD SERVICIOS: ELIMINAR

# Solo permite solicitudes POST.
# Evita que un simple enlace GET elimine registros.
@require_POST

# Solo el administrador puede eliminar servicios.
@requiere_rol("ADMINISTRADOR")
def eliminar_servicio(request, id):

    try:
        # Agrupa las operaciones en una transacción.
        with transaction.atomic():

            # Busca el servicio por su ID.
            # Si no existe, devuelve un error 404.
            servicio = get_object_or_404(Servicios, pk=id)

            # Comprueba si hay citas relacionadas con este servicio.
            # exists() devuelve True si encuentra al menos una.
            if Citas.objects.filter(servicios=servicio).exists():

                # Evita eliminar un servicio que ya tiene citas asociadas.
                # Así se protegen los registros históricos.
                messages.warning(
                    request,
                    f"No es posible eliminar el servicio "
                    f"'{servicio.nombre}' porque tiene citas asociadas. "
                    "Puedes desactivarlo para ocultarlo del catálogo."
                )

                # Regresa a la lista sin eliminar el registro.
                return redirect("agenda:ver_servicio")

            # Conserva el nombre y la fotografía antes de eliminar el objeto.
            # Así podemos usar el nombre en el mensaje posterior
            # y eliminar el archivo después de confirmar la transacción.
            nombre_servicio = servicio.nombre
            nombre_imagen = (
                servicio.imagen.name if servicio.imagen else None
            )
            almacen_imagen = (
                servicio.imagen.storage if servicio.imagen else None
            )

            # Elimina el servicio de la base de datos.
            servicio.delete()

            # Programa la eliminación de la fotografía después
            # de confirmar la transacción de la base de datos.
            if nombre_imagen and almacen_imagen:
                transaction.on_commit(
                    lambda: almacen_imagen.delete(nombre_imagen)
                )

            # Confirma al administrador que la eliminación se realizó.
            messages.success(
                request,
                f"Servicio '{nombre_servicio}' eliminado correctamente."
            )

    # Captura errores por restricciones de integridad.
    # Por ejemplo, si otro registro impide eliminar este servicio.
    except IntegrityError:
        messages.error(
            request,
            "No es posible eliminar el servicio porque está asociado "
            "a otros registros."
        )

    # Captura otros errores relacionados con la base de datos.
    except DatabaseError:
        messages.error(
            request,
            "Ocurrió un error en la base de datos al intentar eliminar el servicio."
        )

    # Vuelve a la lista después de la operación.
    return redirect("agenda:ver_servicio")


# CRUD SERVICIOS: ACTUALIZAR

# Permite GET para mostrar el formulario con los datos actuales
# y POST para guardar los cambios.
@require_http_methods(["GET", "POST"])

# Solo el administrador puede modificar servicios.
@requiere_rol("ADMINISTRADOR")
def actualizar_servicio(request, id):

    # Busca el servicio que se desea editar.
    # Si el ID no existe, devuelve un error 404.
    servicio = get_object_or_404(Servicios, pk=id)

    # Si el administrador envió el formulario, procesa los cambios.
    if request.method == "POST":

        # Recupera los datos nuevos enviados por el formulario.
        nombre = request.POST.get("nombre", "").strip()
        precio = request.POST.get("precio", "").strip()
        descripcion = request.POST.get("descripcion", "").strip()
        duracion = request.POST.get("duracion", "").strip()

        # Obtiene la fotografía nueva y comprueba si se desea eliminar
        # la fotografía que ya tiene el servicio.
        imagen_nueva = request.FILES.get("imagen")
        eliminar_imagen = (
            request.POST.get("eliminar_imagen") == "on"
        )

        # Comprueba que la fotografía nueva sea válida, si se adjuntó.
        try:
            validar_imagen_servicio(imagen_nueva)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect(
                "agenda:actualizar_servicio",
                id=servicio.id
            )

        # En la edición no se usa un valor predeterminado:
        # el formulario debe enviar la comisión seleccionada.
        porcentaje_comision = request.POST.get(
            "porcentaje_comision", ""
        ).strip()

        # Obtiene el estado seleccionado en el formulario.
        estado = request.POST.get("estado", "").strip()

        # Comprueba los campos obligatorios.
        if not nombre or not precio or not duracion:
            messages.error(
                request,
                "Completa los campos obligatorios del servicio."
            )

            # Regresa al formulario del mismo servicio.
            return redirect(
                "agenda:actualizar_servicio", id=servicio.id
            )

        try:
            # Convierte los valores numéricos.
            precio = int(precio)
            duracion = int(duracion)
            porcentaje_comision = int(porcentaje_comision)

            # Valida que el precio y la duración sean positivos.
            if precio <= 0 or duracion <= 0:
                raise ValueError

            # Valida el rango de la comisión.
            if not 0 <= porcentaje_comision <= 100:
                raise ValueError

            # Comprueba que el estado pertenezca a las opciones permitidas.
            if estado not in dict(Servicios.ESTADOS):
                raise ValueError

            # Agrupa las modificaciones en una transacción.
            with transaction.atomic():

                # Guarda la referencia de la fotografía anterior
                # para eliminarla únicamente si cambia o se quita.
                imagen_anterior = (
                    servicio.imagen.name if servicio.imagen else None
                )
                almacen_imagen = (
                    servicio.imagen.storage if servicio.imagen else None
                )

                # Asigna cada valor nuevo al objeto existente.
                servicio.nombre = nombre
                servicio.precio = precio
                servicio.descripcion = descripcion
                servicio.duracion = duracion
                servicio.porcentaje_comision = porcentaje_comision
                servicio.estado = estado

                # Si se adjuntó una fotografía nueva, reemplaza la anterior.
                # Si no se adjuntó y se marcó eliminar, quita la fotografía.
                # Si no se hizo ninguna de las dos cosas, la conserva.
                if imagen_nueva:
                    servicio.imagen = imagen_nueva
                elif eliminar_imagen:
                    servicio.imagen = None

                # Guarda los cambios del objeto existente.
                servicio.save()

                # Comprueba cuál es el nombre de la fotografía después
                # de guardar para determinar si cambió o se eliminó.
                imagen_actual = (
                    servicio.imagen.name if servicio.imagen else None
                )

                # Programa la eliminación de la fotografía anterior
                # solo después de confirmar la transacción.
                if (
                    imagen_anterior
                    and almacen_imagen
                    and imagen_anterior != imagen_actual
                ):
                    transaction.on_commit(
                        lambda: almacen_imagen.delete(imagen_anterior)
                    )

            # Informa que la actualización fue exitosa.
            messages.success(
                request,
                f"Servicio '{servicio.nombre}' actualizado correctamente."
            )

        # Informa de datos no válidos o conversiones incorrectas.
        except ValueError:
            messages.error(
                request,
                "Verifica los valores ingresados. El precio y la "
                "duración deben ser mayores que cero y la comisión "
                "debe estar entre 0 y 100."
            )

            # Mantiene al administrador en el formulario para corregir.
            return redirect(
                "agenda:actualizar_servicio", id=servicio.id
            )

        # Informa de un error de base de datos.
        except DatabaseError:
            messages.error(
                request,
                "Ocurrió un error en la base de datos al actualizar."
            )

        # Si termina el procesamiento, vuelve a la lista.
        return redirect("agenda:ver_servicio")

    # Si la solicitud es GET, muestra el formulario con los datos actuales.
    # La plantilla podrá rellenar los campos usando la variable "datos".
    return render(
        request,
        "servicio/formulario_servicio.html",
        {"datos": servicio}
    )

#CRUD INVENTARIO
@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
def ver_inventario(request):
    try:
        # Capturamos la categoría seleccionada desde los botones de filtro de la URL
        categoria_seleccionada = request.GET.get('categoria', 'todos')

        # Filtramos los productos según la categoría o traemos todos
        if categoria_seleccionada and categoria_seleccionada != 'todos':
            i = Inventario.objects.filter(categoria=categoria_seleccionada)
        else:
            i = Inventario.objects.all()

        # Definimos la lista de categorías para los botones de filtro superior
        lista_categorias = [
            {'nombre': 'Esmaltes y Geles'},
            {'nombre': 'Sistemas Artificiales'},
            {'nombre': 'Herramientas'},
            {'nombre': 'Decoraciones'},
            {'nombre': 'Preparadores'},
        ]

        contexto = {
            "datos": i,
            "lista_categorias": lista_categorias,
            "categoria_actual": categoria_seleccionada
        }
    except DatabaseError:
        # Control de excepciones: Evita un error 500 si la base de datos presenta fallas temporales
        i = []
        contexto = {
            "datos": i,
            "lista_categorias": [],
            "categoria_actual": 'todos'
        }
        messages.error(request, "Ocurrió un error al intentar cargar el inventario.")

    return render(request, "inventario/inventario.html", contexto)

@require_http_methods(["GET", "POST"])  # Seguridad: Restringe a métodos HTTP estándar permitidos
@requiere_rol("ADMINISTRADOR")
def crear_inventario(request):
    if request.method == "POST":
        # Capturar y limpiar los campos enviados por POST
        nombre = request.POST.get('nombre', '').strip()
        categoria = request.POST.get('categoria', '').strip()
        cantidad = request.POST.get('cantidad', '').strip()
        stock_minimo = request.POST.get('stock_minimo', '').strip()

        # Capturar la imagen enviada por FILES (puede venir vacía si no se selecciona ninguna)
        imagen = request.FILES.get('imagen')

        # Validación de campos obligatorios (excluimos la imagen ya que es opcional)
        if not nombre or not categoria or not cantidad or not stock_minimo:
            messages.error(request, "Por favor completa todos los campos obligatorios del inventario.")
            return redirect("agenda:crear_inventario")

        try:
            # Robustez: Transacción atómica para blindar la inserción en base de datos
            with transaction.atomic():
                i = Inventario(
                    nombre=nombre,
                    categoria=categoria,
                    cantidad=cantidad,
                    stock_minimo=stock_minimo,
                    imagen=imagen  # <--- ¡Aquí asignamos la imagen correctamente!
                )
                i.save()

                transaction.on_commit(
                    lambda producto_id=i.pk: notificar_inventario_bajo(
                        Inventario.objects.get(pk=producto_id)
                    )
                )

                messages.success(request, f"Producto '{nombre}' agregado correctamente.")

        except DatabaseError:
            # Control específico ante fallos de base de datos
            messages.error(request, "Ocurrió un error en la base de datos al intentar guardar el producto.")
        except Exception as e:
            # Control genérico ante cualquier eventualidad imprevista
            logger.error(f"Error inesperado al crear inventario: {str(e)}")
            messages.error(request, "Ocurrió un error inesperado al procesar la solicitud.")

        return redirect("agenda:ver_inventario")

    # Si la petición es GET, renderizamos el formulario con normalidad
    return render(request, "inventario/formulario_inventario.html")


@require_POST  # Seguridad crítica: Impide que se eliminen productos mediante una petición GET o enlaces directos
@requiere_rol("ADMINISTRADOR")
def eliminar_inventario(request, id):
    # Control de seguridad: Validar existencia del ID antes de procesar
    if not id:
        messages.error(request, "Identificador de producto no válido.")
        return redirect("agenda:ver_inventario")

    try:
        # Robustez: Transacción atómica combinada con get_object_or_404 para mayor limpieza
        with transaction.atomic():
            i = get_object_or_404(Inventario, pk=id)
            nombre_prod = i.nombre
            i.delete()
            messages.success(request, f"Producto '{nombre_prod}' se eliminó correctamente.")

    except IntegrityError:
        # Control de integridad: Salta si el producto está vinculado a otras tablas del sistema
        messages.info(request, "No es posible eliminar el producto porque tiene registros asociados.")
    except Exception as e:
        # Control genérico ante cualquier eventualidad imprevista
        logger.error(f"Error inesperado al eliminar inventario: {str(e)}")
        messages.error(request, "Ocurrió un error inesperado al intentar eliminar el producto.")

    return redirect("agenda:ver_inventario")


@login_required(login_url="agenda:login")
def lista_movimientos(request):
    movimientos = MovimientoInventario.objects.select_related('producto').all().order_by('-fecha')
    return render(request, 'inventario/movimientos.html', {'movimientos': movimientos})


@login_required(login_url="agenda:login")
@transaction.atomic
def registrar_movimiento(request):
    # --- SI LA PETICIÓN ES POST: PROCESAR EL FORMULARIO ---
    if request.method == 'POST':
        producto_id = request.POST.get('producto')
        tipo = request.POST.get('tipo')
        cantidad_str = request.POST.get('cantidad')
        motivo = request.POST.get('motivo', '').strip()

        # 1. Validar tipo de movimiento
        if tipo not in ['Entrada', 'Salida']:
            messages.error(request, "Tipo de movimiento no válido.")
            return redirect('agenda:lista_movimientos')

        # 2. Validar existencia del producto
        producto = get_object_or_404(Inventario, id=producto_id)

        # 3. Validar cantidad numérica y positiva
        try:
            cantidad = int(cantidad_str)
            if cantidad <= 0:
                raise ValueError("La cantidad debe ser mayor a cero.")
        except (TypeError, ValueError):
            messages.error(request, "La cantidad ingresada no es válida.")
            return redirect('agenda:registrar_movimiento')

        # 4. Validar motivo obligatorio
        if not motivo or len(motivo) < 3:
            messages.error(request, "Debes proporcionar un motivo válido (mínimo 3 caracteres).")
            return redirect('agenda:registrar_movimiento')

        # 5. Validación de stock en salidas
        if tipo == 'Salida' and producto.cantidad < cantidad:
            messages.error(request, f"Acción denegada: Stock insuficiente. Stock actual de '{producto.nombre}': {producto.cantidad}.")
            return redirect('agenda:registrar_movimiento')

        # 6. Actualizar inventario
        if tipo == 'Entrada':
            producto.cantidad += cantidad
        elif tipo == 'Salida':
            producto.cantidad -= cantidad

        producto.save()

        # 7. Crear el registro del movimiento
        MovimientoInventario.objects.create(
            producto=producto,
            tipo=tipo,
            cantidad=cantidad,
            motivo=motivo
        )

        transaction.on_commit(
            lambda producto_id=producto.pk: notificar_inventario_bajo(
                Inventario.objects.get(pk=producto_id)
            )
        )

        messages.success(request, f"Movimiento de {tipo.lower()} registrado con éxito para '{producto.nombre}'.")
        return redirect('agenda:lista_movimientos')

    # --- SI LA PETICIÓN ES GET: MOSTRAR EL FORMULARIO ---
    productos = Inventario.objects.all().order_by('nombre')

    # Ajusta la ruta exacta según cómo tengas estructurada la carpeta dentro de templates:
    # Ejemplo A: Si está directamente en 'templates/inventario/registrar_movimiento.html'
    return render(request, 'inventario/registrar_movimientos.html', {
        'productos': productos
    })


@require_http_methods(["GET", "POST"])  # Seguridad: Restringe a métodos HTTP estándar permitidos
@requiere_rol("ADMINISTRADOR")
def actualizar_inventario(request, id):
    # Control de seguridad: Validar que el ID no esté vacío
    if not id:
        messages.error(request, "Identificador de producto no válido.")
        return redirect("agenda:ver_inventario")

    # Obtener el producto de forma segura
    try:
        i = Inventario.objects.get(pk=id)
    except Inventario.DoesNotExist:
        messages.warning(request, "El producto no existe.")
        return redirect("agenda:ver_inventario")

    if request.method == "POST":
        # Capturar y limpiar los campos enviados en el formulario
        nombre = request.POST.get('nombre', '').strip()
        categoria = request.POST.get('categoria', '').strip()
        cantidad = request.POST.get('cantidad', '').strip()
        stock_minimo = request.POST.get('stock_minimo', '').strip()

        # Capturar la imagen nueva enviada por FILES (si el usuario seleccionó una)
        imagen = request.FILES.get('imagen')

        # Validación de campos obligatorios
        if not nombre or not categoria or not cantidad or not stock_minimo:
            messages.error(request, "Por favor completa todos los campos obligatorios del inventario.")
            return redirect("agenda:ver_inventario")

        try:
            # Robustez: Transacción atómica para garantizar una actualización segura
            with transaction.atomic():
                i.nombre = nombre
                i.categoria = categoria
                i.cantidad = cantidad
                i.stock_minimo = stock_minimo

                # ¡Importante! Solo actualizamos la imagen si el usuario subió una nueva
                if imagen:
                    i.imagen = imagen

                i.save()

                transaction.on_commit(
                    lambda producto_id=i.pk: notificar_inventario_bajo(
                        Inventario.objects.get(pk=producto_id)
                    )
                )

                messages.success(request, f"Producto '{i.nombre}' actualizado correctamente.")

        except DatabaseError:
            # Control específico ante fallos de base de datos
            messages.error(request, "Ocurrió un error en la base de datos al intentar actualizar el producto.")
        except Exception as e:
            # Control genérico ante eventualidades imprevistas
            logger.error(f"Error inesperado al actualizar inventario: {str(e)}")
            messages.error(request, "Ocurrió un error inesperado al procesar la actualización.")

        return redirect("agenda:ver_inventario")
    else:
        # Petición GET: renderizamos el formulario con el objeto existente
        contexto = {
            "datos": i
        }
        return render(request, "inventario/formulario_inventario.html", contexto)






# ---- VISTA RECIBO ----
@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
def recibo(request, id):
    if not id:
        messages.error(request, "Identificador de cita no válido.")
        return redirect("agenda:mis_citas")

    try:
        cliente = Clientes.objects.filter(user=request.user).first()

        if not cliente:
            messages.error(request, "No se encontró tu perfil de cliente.")
            return redirect("agenda:mis_citas")

        cita = get_object_or_404(
            Citas.objects.select_related(
                "cliente",
                "cliente__user",
                "manicurista",
                "servicios",
                "descuento",
            ),
            pk=id,
            cliente=cliente,
        )

        # Buscar un pago efectivamente realizado
        pago = cita.pagos.filter(
            estado="Realizado"
        ).order_by("-fecha_pago", "-id").first()

        if cita.estado != "completada" or not pago:
            messages.warning(
                request,
                "El recibo solo está disponible para citas completadas y pagadas."
            )
            return redirect("agenda:mis_citas")

        # Crear o recuperar el recibo y generar la notificación si falta
        recibo_obj = crear_recibo_y_notificar(cita)

        # Validar que se haya podido obtener el recibo
        if recibo_obj is None:
            messages.warning(
                request,
                "No fue posible generar el recibo de esta cita."
            )
            return redirect("agenda:mis_citas")

        contexto = {
            "recibo": recibo_obj,
            "cita": cita,
            "pago": pago,
        }

    except DatabaseError:
        messages.error(
            request,
            "Ocurrió un error al intentar generar el recibo de la cita."
        )
        return redirect("agenda:mis_citas")

    return render(request, "recibo/recibo.html", contexto)




#-----CRUD GASTOS----
@requiere_rol("ADMINISTRADOR")
def ver_gasto(request):
    try:
        # Robustez: Consulta segura de todos los registros de gastos
        g = Gastos.objects.all()

        contexto = {
            "datos": g
        }
    except DatabaseError:
        # Control de excepciones: Previene un error 500 si la base de datos presenta fallas temporales
        g = []
        contexto = {
            "datos": g
        }
        messages.error(request, "Ocurrió un error al intentar cargar el listado de gastos.")

    return render(request, "gastos/gastos.html", contexto)


@require_http_methods(["GET", "POST"])  # Seguridad: Restringe a métodos HTTP estándar permitidos
@requiere_rol("ADMINISTRADOR")
def crear_gastos(request):
    if request.method == "POST":
        # Capturar y limpiar los campos enviados por POST
        concepto = request.POST.get('concepto', '').strip()
        valor = request.POST.get('valor', '').strip()
        fecha = request.POST.get('fecha', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()

        # Validación de campos obligatorios para evitar registros vacíos o corruptos
        if not concepto or not valor or not fecha:
            messages.error(request, "Por favor completa todos los campos obligatorios del gasto.")
            return redirect("agenda:gastos")

        try:
            # Robustez: Transacción atómica para blindar la inserción en base de datos
            with transaction.atomic():
                g = Gastos(
                    concepto=concepto,
                    valor=valor,
                    fecha=fecha,
                    descripcion=descripcion,
                )
                g.save()
                messages.success(request, "Gasto registrado correctamente.")

        except DatabaseError:
            # Control específico ante fallos de base de datos
            messages.error(request, "Ocurrió un error en la base de datos al intentar registrar el gasto.")
        except Exception as e:
            # Control genérico ante cualquier eventualidad imprevista
            messages.error(request, "Ocurrió un error inesperado al procesar la solicitud.")

        return redirect("agenda:gastos")

    # Si la petición es GET, renderizamos el formulario con normalidad
    return render(request, "gastos/formulario_gastos.html")

@require_POST  # Seguridad crítica: Impide que se eliminen gastos mediante una petición GET o enlaces directos
@requiere_rol("ADMINISTRADOR")
def eliminar_gastos(request, id):
    # Control de seguridad: Validar existencia del ID antes de procesar
    if not id:
        messages.error(request, "Identificador de gasto no válido.")
        return redirect("agenda:gastos")

    try:
        # Robustez: Transacción atómica combinada con get_object_or_404 para mayor limpieza
        with transaction.atomic():
            g = get_object_or_404(Gastos, pk=id)
            g.delete()
            messages.success(request, "Gasto eliminado correctamente.")

    except IntegrityError:
        # Control de integridad: Salta si el gasto está vinculado a restricciones foráneas
        messages.info(request, "No es posible eliminar el gasto porque tiene registros asociados.")
    except Exception as e:
        # Control genérico ante cualquier eventualidad imprevista
        messages.error(request, "Ocurrió un error inesperado al intentar eliminar el gasto.")

    return redirect("agenda:gastos")


@require_http_methods(["GET", "POST"])  # Seguridad: Restringe a métodos HTTP estándar permitidos
@requiere_rol("ADMINISTRADOR")
def actualizar_gastos(request, id):
    # Control de seguridad: Validar que el ID no esté vacío
    if not id:
        messages.error(request, "Identificador de gasto no válido.")
        return redirect("agenda:gastos")

    # Obtener el gasto de forma segura manteniendo tu manejo de excepciones original
    try:
        g = Gastos.objects.get(pk=id)
    except Gastos.DoesNotExist:
        messages.warning(request, "El gasto no existe.")
        return redirect("agenda:gastos")

    if request.method == "POST":
        # Capturar y limpiar los campos enviados en el formulario
        concepto = request.POST.get('concepto', '').strip()
        valor = request.POST.get('valor', '').strip()
        fecha = request.POST.get('fecha', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()

        # Validación de campos obligatorios
        if not concepto or not valor or not fecha:
            messages.error(request, "Por favor completa todos los campos obligatorios del gasto.")
            return redirect("agenda:gastos")

        try:
            # Robustez: Transacción atómica para garantizar una actualización segura en base de datos
            with transaction.atomic():
                g.concepto = concepto
                g.valor = valor
                g.fecha = fecha
                g.descripcion = descripcion
                g.save()

                messages.success(request, "Gasto actualizado correctamente.")

        except DatabaseError:
            # Control específico ante fallos de base de datos
            messages.error(request, "Ocurrió un error en la base de datos al intentar actualizar el gasto.")
        except Exception as e:
            # Control genérico ante eventualidades imprevistas
            messages.error(request, "Ocurrió un error inesperado al procesar la actualización.")

        return redirect("agenda:gastos")
    else:
        # Petición GET: reutilizamos directamente el objeto 'g' que ya consultamos al inicio
        contexto = {
            "datos": g
        }
        return render(request, "gastos/formulario_gastos.html", contexto)


@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_POST
def registrar_gasto_financiero(request):
    """
    Registra un egreso/gasto directamente desde los libros contables.
    """
    if request.POST.get('accion') == 'registrar_gasto':
        concepto = request.POST.get('concepto', '').strip()
        referencia = request.POST.get('referencia', '').strip()
        valor = request.POST.get('valor', '').strip()
        fecha = request.POST.get('fecha', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()

        if not concepto or not valor or not fecha:
            messages.error(request, "Por favor completa los campos obligatorios del gasto.")
            return redirect('agenda:contabilidad')

        try:
            with transaction.atomic():
                Gastos.objects.create(
                    concepto=concepto,
                    referencia=referencia,
                    valor=int(valor),
                    fecha=fecha,
                    descripcion=descripcion
                )
            messages.success(request, "Gasto registrado correctamente en el libro de egresos.")
        except Exception as e:
            messages.error(request, "Ocurrió un error al intentar guardar el gasto.")

    return redirect('agenda:contabilidad')

# ----CRUD PAGOS----

@requiere_rol("ADMINISTRADOR")
def ver_pagos(request):
    try:
        # Robustez: Consulta segura de todos los registros de pagos
        p = Pagos.objects.all()

        contexto = {
            "datos": p
        }
    except DatabaseError:
        # Control de excepciones: Previene un error 500 si la base de datos presenta fallas temporales
        p = []
        contexto = {
            "datos": p
        }
        messages.error(request, "Ocurrió un error al intentar cargar el listado de pagos.")

    return render(request, "pago/pago.html", contexto)


@require_http_methods(["GET", "POST"])  # Seguridad: Restringe a métodos HTTP estándar permitidos
@requiere_rol("ADMINISTRADOR")
def crear_pago(request):
    if request.method == "POST":
        # Capturar y limpiar los campos enviados por POST
        citas_id = request.POST.get('citas', '').strip()
        metodo_pago = request.POST.get('metodo_pago', '').strip()
        estado = request.POST.get('estado', '').strip()
        referencia = request.POST.get('referencias', '').strip()

        # Validación de campos obligatorios
        if not citas_id or not metodo_pago or not estado:
            messages.error(request, "Por favor completa todos los campos obligatorios del pago.")
            return redirect("agenda:pagos")

        try:
            # Robustez: Transacción atómica combinada con get_object_or_404 para verificar la cita de forma segura
            with transaction.atomic():
                citas = get_object_or_404(Citas, pk=citas_id)

                # Validación de duplicidad con bloqueo transaccional
                existe = Pagos.objects.filter(citas_id=citas_id).exists()
                if existe:
                    messages.warning(request, "Pago registrado con anterioridad.")
                    return redirect("agenda:pagos")

                p = Pagos(
                    citas=citas,
                    metodo_pago=metodo_pago,
                    estado=estado,
                    referencia=referencia,
                    valor=citas.total
                )
                p.save()

                # Crear el recibo y notificar al cliente solo si el pago fue realizado
                # El helper también debe verificar que la cita esté completada
                if p.estado == "Realizado":
                    crear_recibo_y_notificar(citas)

                messages.success(request, "Pago registrado correctamente.")

        except DatabaseError:
            # Control específico ante fallos de base de datos
            messages.error(request, "Ocurrió un error en la base de datos al intentar registrar el pago.")
        except Exception as e:
            # Control genérico ante eventualidades imprevistas
            logger.error(f"Error inesperado en pagos: {str(e)}")
            messages.error(request, "Ocurrió un error inesperado al procesar la solicitud.")

        return redirect("agenda:pagos")

    else:
        try:
            # Petición GET: consulta segura de las citas disponibles para asociar en el formulario
            citas = Citas.objects.all()
            contexto = {
                "citas": citas
            }
        except DatabaseError:
            citas = []
            contexto = {
                "citas": citas
            }
            messages.error(request, "Ocurrió un error al cargar el listado de citas.")

        return render(request, "pago/formulario_pago.html", contexto)



@require_POST  # Seguridad crítica: Impide que se eliminen pagos mediante peticiones GET o enlaces directos
@requiere_rol("ADMINISTRADOR")
def eliminar_pago(request, id):
    # Control de seguridad: Validar existencia del ID antes de procesar
    if not id:
        messages.error(request, "Identificador de pago no válido.")
        return redirect("agenda:pagos")

    try:
        # Robustez: Transacción atómica combinada con get_object_or_404 para mayor limpieza
        with transaction.atomic():
            p = get_object_or_404(Pagos, pk=id)
            p.delete()
            messages.success(request, "Pago eliminado correctamente.")

    except IntegrityError:
        # Control de integridad: Salta si el pago tiene dependencias o restricciones foráneas
        messages.info(request, "No es posible eliminar el pago porque tiene registros asociados.")
        return redirect("agenda:pagos")
    except Exception as e:
        # Control genérico ante cualquier eventualidad imprevista
        logger.error(f"Error inesperado en pagos: {str(e)}")
        messages.error(request, "Ocurrió un error inesperado al intentar eliminar el pago.")
        return redirect("agenda:pagos")


@require_http_methods(["GET", "POST"])  # Seguridad: Restringe a métodos HTTP estándar permitidos
@requiere_rol("ADMINISTRADOR")
def actualizar_pago(request, id):
    # Control de seguridad: Validar que el ID no esté vacío
    if not id:
        messages.error(request, "Identificador de pago no válido.")
        return redirect("agenda:pagos")

    pago = get_object_or_404(Pagos, pk=id)

    if request.method == "POST":
        # Capturar y limpiar los campos enviados en el formulario
        citas_id = request.POST.get("citas", "").strip()
        metodo_pago = request.POST.get("metodo_pago", "").strip()
        estado = request.POST.get("estado", "").strip()
        referencia = request.POST.get("referencia", "").strip()

        # Validación de campos obligatorios
        if not citas_id or not metodo_pago or not estado:
            messages.error(request, "Por favor completa todos los campos obligatorios del pago.")
            return redirect("agenda:actualizar_pago", id=id)

        try:
            # Robustez: Transacción atómica para garantizar la consistencia al actualizar
            with transaction.atomic():
                # Buscar la cita seleccionada de forma segura
                cita = get_object_or_404(Citas, pk=citas_id)

                if cita.estado == 'cancelada':
                    messages.error(request, "No se puede asociar un pago a una cita cancelada.")
                    return redirect("agenda:actualizar_pago", id=id)

                # Actualizar las propiedades del pago
                pago.citas = cita
                pago.metodo_pago = metodo_pago
                pago.estado = estado
                pago.referencia = referencia
                pago.valor = cita.total  # Actualiza automáticamente el valor acorde al total de la cita

                pago.save()

                # Crear el recibo y notificar al cliente solo si el pago fue realizado
                # El helper también debe verificar que la cita esté completada
                if pago.estado == "Realizado":
                    crear_recibo_y_notificar(cita)

                messages.success(request, "Pago actualizado correctamente.")

        except DatabaseError:
            messages.error(request, "Ocurrió un error en la base de datos al intentar actualizar el pago.")
            return redirect("agenda:actualizar_pago", id=id)
        except Exception as e:
            logger.error(f"Error inesperado al actualizar el pago: {str(e)}")
            messages.error(request, "Ocurrió un error inesperado al procesar la actualización.")
            return redirect("agenda:actualizar_pago", id=id)

        return redirect("agenda:pagos")

    # Petición GET: Carga segura de las citas para el formulario
    try:
        citas = Citas.objects.all()
    except DatabaseError:
        citas = []
        messages.error(request, "Ocurrió un error al cargar el listado de citas.")

    contexto = {
        "datos": pago,
        "citas": citas
    }
    return render(request, "pago/formulario_pago.html", contexto)




# ----------------- MÓDULO DE CONTABILIDAD ----------------
@requiere_rol("ADMINISTRADOR")
def modulo_contabilidad(request):
    hoy = now().date()

    # --- PROCESAR FORMULARIO DE NUEVO GASTO (EGRESO) ---
    if request.method == 'POST' and request.POST.get('accion') == 'registrar_gasto':
        concepto = request.POST.get('concepto', '').strip()
        referencia = request.POST.get('referencia', '').strip()
        valor_str = request.POST.get('valor', '').strip()
        fecha_str = request.POST.get('fecha', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()

        if not concepto or not valor_str or not fecha_str:
            messages.error(request, "Por favor completa los campos obligatorios del gasto.")
        else:
            try:
                with transaction.atomic():
                    Gastos.objects.create(
                        concepto=concepto,
                        referencia=referencia,
                        valor=int(valor_str),
                        fecha=fecha_str,
                        descripcion=descripcion
                    )
                messages.success(request, "Gasto registrado correctamente en el libro de egresos.")
            except Exception as e:
                messages.error(request, "Ocurrió un error al intentar registrar el gasto.")

        # Redirigir conservando los parámetros GET actuales si los hubiera, o recargando la vista
        return redirect('agenda:modulo_contabilidad')

    pagos_mes = Pagos.objects.none()

    # Obtenemos los parámetros de forma segura limpiando puntos o comas
    mes_str = request.GET.get('mes', str(hoy.month)).replace('.', '').replace(',', '')
    anio_str = request.GET.get('anio', str(hoy.year)).replace('.', '').replace(',', '')

    try:
        mes_actual = int(mes_str)
        anio_actual = int(anio_str)
    except ValueError:
        mes_actual = hoy.month
        anio_actual = hoy.year

    try:
        # 1. INGRESOS: Pagos con estado 'Realizado' filtrados por la fecha del pago (o de la cita)
        pagos_mes = Pagos.objects.filter(
            fecha_pago__month=mes_actual,
            fecha_pago__year=anio_actual,
            estado='Realizado'
        ).select_related('citas', 'citas__servicios')

        ingresos_totales = pagos_mes.aggregate(total=Sum('valor'))['total'] or 0

        # Desglose por método de pago según tus choices (Efectivo, Nequi, Bancolombia, Transferencia)
        ingresos_efectivo = pagos_mes.filter(metodo_pago='Efectivo').aggregate(t=Sum('valor'))['t'] or 0
        ingresos_nequi = pagos_mes.filter(metodo_pago='Nequi').aggregate(t=Sum('valor'))['t'] or 0
        ingresos_bancolombia = pagos_mes.filter(metodo_pago='Bancolombia').aggregate(t=Sum('valor'))['t'] or 0
        ingresos_transferencia = pagos_mes.filter(metodo_pago='Transferencia').aggregate(t=Sum('valor'))['t'] or 0

        # 2. GASTOS: Filtrados por fecha en el mes y año seleccionados usando tu modelo Gastos
        gastos_mes = Gastos.objects.filter(
            fecha__month=mes_actual,
            fecha__year=anio_actual
        )
        gastos_totales = gastos_mes.aggregate(total=Sum('valor'))['total'] or 0

        # 3. COMISIONES DE MANICURISTAS: Basado en citas completadas en el mes y el porcentaje del servicio
        citas_completadas = Citas.objects.filter(
            fecha__month=mes_actual,
            fecha__year=anio_actual,
            estado='completada'
        ).select_related('manicurista', 'servicios')

        comisiones_totales = 0
        resumen_manicuristas = {}

        for cita in citas_completadas:
            manicurista = cita.manicurista
            # Usa el porcentaje configurado en tu modelo Servicios (por defecto 50%)
            porcentaje = cita.servicios.porcentaje_comision / 100
            comision_cita = float(cita.total) * porcentaje

            comisiones_totales += comision_cita

            nombre_completo = f"{manicurista.nombre} {manicurista.apellido}"
            if nombre_completo not in resumen_manicuristas:
                resumen_manicuristas[nombre_completo] = {
                    'servicios_realizados': 0,
                    'total_comision': 0
                }

            resumen_manicuristas[nombre_completo]['servicios_realizados'] += 1
            resumen_manicuristas[nombre_completo]['total_comision'] += comision_cita

        # 4. BALANCE GENERAL / UTILIDAD NETA
        utilidad_neta = float(ingresos_totales) - float(gastos_totales) - float(comisiones_totales)

    except Exception as e:
        ingresos_totales = 0
        gastos_totales = 0
        comisiones_totales = 0
        utilidad_neta = 0
        gastos_mes = []
        resumen_manicuristas = {}
        ingresos_efectivo = ingresos_nequi = ingresos_bancolombia = ingresos_transferencia = 0
        messages.error(request, "Ocurrió un error al calcular los datos contables del período.")

    contexto = {
        "mes_actual": mes_actual,
        "anio_actual": anio_actual,
        "ingresos_totales": ingresos_totales,
        "ingresos_efectivo": ingresos_efectivo,
        "ingresos_nequi": ingresos_nequi,
        "ingresos_bancolombia": ingresos_bancolombia,
        "ingresos_transferencia": ingresos_transferencia,
        "gastos_totales": gastos_totales,
        "pagos_lista": pagos_mes,
        "gastos_lista": gastos_mes,
        "comisiones_totales": comisiones_totales,
        "resumen_manicuristas": resumen_manicuristas,
        "utilidad_neta": utilidad_neta,
    }

    return render(request, "administrador/contabilidad.html", contexto)



    # -----------CALENDARIO--------
from django.http import JsonResponse

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR", "CLIENTE", "MANICURISTA")
@require_GET
def ver_calendario(request):
    try:
        rol_nombre = request.user.perfil.rol.nombre.upper()
    except (AttributeError, Exception):
        messages.error(request, "Tu usuario no tiene un rol asignado.")
        return redirect("agenda:login")

    # Filtrado preventivo de datos según el rol en sesión
    if rol_nombre == "CLIENTE":
        # El cliente solo visualiza la disponibilidad general y sus propias citas
        citas_agenda = Citas.objects.filter(cliente__user=request.user).select_related("servicios", "manicurista")
    elif rol_nombre == "MANICURISTA":
        # La manicurista solo visualiza su propia agenda asignada
        citas_agenda = Citas.objects.filter(manicurista__user=request.user).select_related("servicios", "cliente")
    else:
        # ADMINISTRADOR: Acceso completo a la agenda global
        citas_agenda = Citas.objects.all().select_related("servicios", "cliente", "manicurista")

    contexto = {
        "rol": rol_nombre,
        "citas": citas_agenda
    }

    return render(request, "calendario.html", contexto)

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR", "CLIENTE", "MANICURISTA")
def obtener_citas_json(request):
    citas_data = []

    try:
        rol_nombre = request.user.perfil.rol.nombre.upper()
    except (AttributeError, Exception):
        return JsonResponse([], safe=False)

    # Filtrado estricto según ID y Rol del usuario en sesión (excluyendo canceladas)
    if rol_nombre == "CLIENTE":
        try:
            cliente = Clientes.objects.get(user=request.user)
            # Excluimos las canceladas
            citas = Citas.objects.filter(cliente=cliente).exclude(estado__iexact='cancelada').select_related('servicios', 'manicurista')
        except Clientes.DoesNotExist:
            return JsonResponse([], safe=False)

    elif rol_nombre == "MANICURISTA":
        try:
            manicurista = Manicurista.objects.get(user=request.user)
            # Excluimos las canceladas
            citas = Citas.objects.filter(manicurista=manicurista).exclude(estado__iexact='cancelada').select_related('servicios', 'cliente')
        except Manicurista.DoesNotExist:
            return JsonResponse([], safe=False)

    else:
        # ADMINISTRADOR o superusuario ve todas las citas activas del sistema
        citas = Citas.objects.all().exclude(estado__iexact='Cancelada').select_related('servicios', 'cliente', 'manicurista')

    for cita in citas:
        # Crear timestamp de inicio
        start_dt = datetime.combine(cita.fecha, cita.hora)

        # Duración segura
        if cita.servicios and hasattr(cita.servicios, 'duracion_horas'):
            duracion_min = int(cita.servicios.duracion_horas * 60)
        elif cita.servicios and hasattr(cita.servicios, 'duracion') and cita.servicios.duracion:
            duracion_min = cita.servicios.duracion
        else:
            duracion_min = 60

        end_dt = start_dt + timedelta(minutes=duracion_min)

        if rol_nombre == "CLIENTE":
            titulo = f"💅 {cita.servicios.nombre} - Manicurista: {cita.manicurista.nombre} {cita.manicurista.apellido}"
        else:
            titulo = f"💅 {cita.servicios.nombre} - Clienta: {cita.cliente.nombre} {cita.cliente.apellido}"

        citas_data.append({
            "id": cita.id,
            "title": titulo,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "extendedProps": {
                "cliente": f"{cita.cliente.nombre} {cita.cliente.apellido}",
                "manicurista": f"{cita.manicurista.nombre} {cita.manicurista.apellido}",
                "servicio": cita.servicios.nombre,
                "duracion": f"{duracion_min} minutos",
                "total": f"${cita.total:,}",
                "descripcion_servicio": getattr(cita.servicios, 'descripcion', "Sin descripción."),
                "telefono_cliente": cita.cliente.telefono,
                "telefono_manicurista": cita.manicurista.telefono,
            }
        })

    return JsonResponse(citas_data, safe=False)

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR", "MANICURISTA")
def obtener_citas_cliente_json(request, cliente_id):
    try:
        # Buscamos al cliente por su ID
        cliente = Clientes.objects.get(id=cliente_id)
        # Obtenemos todas sus citas ordenadas por fecha reciente
        citas = Citas.objects.filter(cliente=cliente).select_related('servicios', 'manicurista').order_by('-fecha', '-hora')

        citas_data = []
        for cita in citas:
            total_valor = float(cita.total) if hasattr(cita, 'total') and cita.total else 0.0
            citas_data.append({
                "servicio": cita.servicios.nombre if cita.servicios else "Servicio",
                "fecha": cita.fecha.strftime('%Y-%m-%d') if cita.fecha else "",
                "hora": cita.hora.strftime('%H:%M') if cita.hora else "",
                "estado": getattr(cita, 'estado', 'Programada'),
                "total": total_valor
            })

        return JsonResponse({'citas': citas_data})
    except Clientes.DoesNotExist:
        return JsonResponse({'citas': [], 'error': 'Cliente no encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'citas': [], 'error': str(e)}, status=400)


@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
def mis_descuentos(request):
    """
    Muestra las promociones vigentes y calcula
    si la clienta puede utilizarlas.
    """
    cliente = get_object_or_404(
        Clientes,
        user=request.user
    )

    hoy = timezone.localdate()

    descuentos = Descuentos.objects.filter(
        activo=True,
        fecha_fin__gte=hoy
    ).order_by("fecha_inicio", "fecha_fin")

    for descuento in descuentos:
        # Estado inicial.
        descuento.estado_cliente = "disponible"

        # La promoción todavía no comienza.
        if descuento.fecha_inicio > hoy:
            descuento.estado_cliente = "proximamente"
            continue

        # Revisar si ya utilizó o reservó la promoción.
        if descuento.tipo == Descuentos.Tipo.CUMPLEAÑOS:
            nacimiento = cliente.fecha_nacimiento

            if not nacimiento:
                descuento.estado_cliente = "sin_fecha_nacimiento"
                continue

            ya_utilizo = Citas.objects.filter(
                cliente=cliente,
                descuento__tipo=Descuentos.Tipo.CUMPLEAÑOS,
                fecha__year=hoy.year
            ).exclude(
                estado__iexact="cancelada"
            ).exists()

            if ya_utilizo:
                descuento.estado_cliente = "utilizado"

        elif descuento.tipo == Descuentos.Tipo.PRIMERA_CITA:
            ya_completo_cita = Citas.objects.filter(
                cliente=cliente,
                estado__iexact="completada"
            ).exists()

            ya_utilizo = Citas.objects.filter(
                cliente=cliente,
                descuento=descuento
            ).exclude(
                estado__iexact="cancelada"
            ).exists()

            if ya_completo_cita or ya_utilizo:
                descuento.estado_cliente = "utilizado"

        else:
            ya_utilizo = Citas.objects.filter(
                cliente=cliente,
                descuento=descuento
            ).exclude(
                estado__iexact="cancelada"
            ).exists()

            if ya_utilizo:
                descuento.estado_cliente = "utilizado"

    # Obtener las preferencias de fecha y hora
    try:
        preferencias = request.user.preferencias_spa
        formato_fecha = preferencias.formato_fecha
        formato_hora = preferencias.formato_hora
    except PreferenciasUsuario.DoesNotExist:
        formato_fecha = "DMY"
        formato_hora = "12"

    contexto = {
        "descuentos": descuentos,
        "hoy": hoy,
        "formato_fecha": formato_fecha,
        "formato_hora": formato_hora,
    }

    return render(
        request,
        "cliente/mis_descuentos.html",
        contexto
    )





@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
@require_http_methods(["GET", "POST"])
def usar_descuento(request, descuento_id):
    cliente = get_object_or_404(
        Clientes,
        user=request.user
    )

    hoy = timezone.localdate()

    # 1. Comprobar que la promoción esté activa y no haya vencido.
    descuento = get_object_or_404(
        Descuentos,
        pk=descuento_id,
        activo=True,
        fecha_fin__gte=hoy
    )

    # 2. Validar si la clienta puede usar esta promoción.

    # 2. Validar condiciones que no dependen de una cita concreta.
    if descuento.tipo == Descuentos.Tipo.PRIMERA_CITA:
        ya_tuvo_cita = Citas.objects.filter(
            cliente=cliente,
            estado__iexact="completada"
        ).exists()

        ya_utilizo_promocion = Citas.objects.filter(
            cliente=cliente,
            descuento=descuento
        ).exclude(
            estado__iexact="cancelada"
        ).exists()

        if ya_tuvo_cita or ya_utilizo_promocion:
            messages.error(
                request,
                "Esta promoción es exclusiva para tu primera cita."
            )
            return redirect("agenda:mis_descuentos")

    elif descuento.tipo == Descuentos.Tipo.CUMPLEAÑOS:
        nacimiento = cliente.fecha_nacimiento

        if not nacimiento:
            messages.error(
                request,
                "Registra tu fecha de nacimiento para utilizar "
                "la promoción de cumpleaños."
            )
            return redirect("agenda:mis_descuentos")

        ya_utilizo_ese_anio = Citas.objects.filter(
            cliente=cliente,
            descuento__tipo=Descuentos.Tipo.CUMPLEAÑOS,
            fecha__year=hoy.year
        ).exclude(
            estado__iexact="cancelada"
        ).exists()

        if ya_utilizo_ese_anio:
            messages.error(
                request,
                "Ya utilizaste tu descuento de cumpleaños este año."
            )
            return redirect("agenda:mis_descuentos")

    else:
        ya_utilizo_promocion = Citas.objects.filter(
            cliente=cliente,
            descuento=descuento
        ).exclude(
            estado__iexact="cancelada"
        ).exists()

        if ya_utilizo_promocion:
            messages.error(
                request,
                "Ya tienes esta promoción reservada o utilizada."
            )
            return redirect("agenda:mis_descuentos")


    # 3. Mostrar únicamente citas futuras sin otro descuento,
    # dentro de la vigencia de la promoción.
    citas_elegibles = Citas.objects.filter(
    cliente=cliente,
    estado="programada",
    fecha__gte=max(hoy, descuento.fecha_inicio),
    fecha__lte=descuento.fecha_fin,
    descuento__isnull=True,
    descuento_aplicado=0
    ).select_related(
        "servicios",
        "manicurista"
    ).order_by("fecha", "hora")

    # 4. Para cumpleaños, la cita debe ser el día y mes exactos.
    if descuento.tipo == Descuentos.Tipo.CUMPLEAÑOS:
        citas_elegibles = citas_elegibles.filter(
            fecha__month=nacimiento.month,
            fecha__day=nacimiento.day
        )

    # 5. Procesar el formulario cuando la clienta selecciona una cita.
    if request.method == "POST":
        cita_id = request.POST.get("cita_id")

        if not cita_id:
            messages.error(request, "Selecciona una cita para continuar.")
            return redirect("agenda:usar_descuento", descuento_id=descuento.id)

        cita = get_object_or_404(
            Citas,
            pk=cita_id,
            cliente=cliente
        )

        error_descuento = validar_uso_descuento(
            cliente,
            descuento,
            cita.fecha
        )

        if error_descuento:
            messages.error(request, error_descuento)
            return redirect("agenda:usar_descuento", descuento_id=descuento.id)


        with transaction.atomic():
            cita = get_object_or_404(
                Citas.objects.select_for_update(),
                pk=cita_id,
                cliente=cliente
            )

            # Comprobar nuevamente que la cita siga disponible.
            if (
                cita.estado != "programada"
                or cita.fecha < hoy
                or cita.descuento_id is not None
                or cita.descuento_aplicado != 0
            ):
                messages.error(
                    request,
                    "Esta cita ya no está disponible para aplicar "
                    "el descuento."
                )
                return redirect(
                    "agenda:usar_descuento",
                    descuento_id=descuento.id
                )

            # La cita debe estar dentro de la vigencia.
            if not (
                descuento.fecha_inicio <= cita.fecha
                <= descuento.fecha_fin
            ):
                messages.error(
                    request,
                    "La fecha de la cita no está dentro de la "
                    "vigencia de la promoción."
                )
                return redirect(
                    "agenda:usar_descuento",
                    descuento_id=descuento.id
                )


            # Validar nuevamente todas las reglas del descuento.
            # Se repite dentro de la transacción para evitar
            # utilizar una promoción que ya fue reservada.
            error_descuento = validar_uso_descuento(
                cliente,
                descuento,
                cita.fecha
            )

            if error_descuento:
                messages.error(request, error_descuento)
                return redirect(
                    "agenda:usar_descuento",
                    descuento_id=descuento.id
                )


            # 6. Calcular el descuento en el servidor.
            from decimal import Decimal, ROUND_HALF_UP

            precio_original = Decimal(str(cita.servicios.precio))

            if descuento.tipo_beneficio == (
                Descuentos.TipoBeneficio.PORCENTAJE
            ):
                valor_descuento = int(
                    (
                        precio_original * descuento.valor
                        / Decimal("100")
                    ).quantize(
                        Decimal("1"),
                        rounding=ROUND_HALF_UP
                    )
                )
            else:
                valor_descuento = int(
                    descuento.valor.quantize(
                        Decimal("1"),
                        rounding=ROUND_HALF_UP
                    )
                )

            # El descuento nunca puede superar el precio del servicio.
            valor_descuento = min(
                valor_descuento,
                int(precio_original)
            )

            if valor_descuento <= 0:
                messages.error(
                    request,
                    "No se pudo calcular un descuento válido."
                )
                return redirect(
                    "agenda:usar_descuento",
                    descuento_id=descuento.id
                )

            # 7. Guardar los valores definitivos de la cita.
            cita.precio_original = int(precio_original)
            cita.descuento_aplicado = valor_descuento
            cita.descuento = descuento
            cita.total = int(precio_original) - valor_descuento

            cita.save(
                update_fields=[
                    "precio_original",
                    "descuento_aplicado",
                    "descuento",
                    "total"
                ]
            )

        # 8. Confirmar que se aplicó.
        request.session.pop("descuento_pendiente_id", None)

        messages.success(
            request,
            "¡Descuento aplicado correctamente a tu cita!"
        )

        return redirect("agenda:mis_descuentos")

    # 9. Si hay citas elegibles, mostrar el selector.
    if citas_elegibles.exists():
        return render(
            request,
            "cliente/usar_descuento.html",
            {
                "descuento": descuento,
                "citas_elegibles": citas_elegibles,
            }
        )

    # 10. Si no hay citas elegibles, guardar la promoción
    # temporalmente para continuar con el flujo de reservas.
    request.session["descuento_pendiente_id"] = descuento.id

    messages.info(
        request,
        "Tu promoción está seleccionada. Agenda una cita "
        "que cumpla las condiciones para utilizarla."
    )

    return redirect("agenda:crear_citas")


@login_required(login_url="agenda:login")
def abrir_notificacion(request, notificacion_id):
    notificacion = get_object_or_404(
        Notificacion,
        id=notificacion_id,
        destinatario=request.user
    )

    # Marcar como leída al abrirla
    if not notificacion.leida:
        notificacion.leida = True
        notificacion.save(update_fields=["leida"])

    # Redirigir únicamente a una ruta interna segura
    destino = notificacion.url

    if destino and url_has_allowed_host_and_scheme(
        destino,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure()
    ):
        return redirect(destino)

    return redirect("agenda:dashboard")



# ==========================================================
# CRUD DE DESCUENTOS
# ==========================================================

def _guardar_datos_descuento(request, descuento=None):
    """
    Valida los datos recibidos y guarda el descuento.
    Se utiliza tanto para crear como para actualizar.
    """

    es_edicion = descuento is not None

    if es_edicion:
        instancia = descuento
    else:
        instancia = Descuentos()

    # Conservar los datos para rellenar el formulario si hay errores.
    datos = {
        "nombre": request.POST.get("nombre", "").strip(),
        "descripcion": request.POST.get("descripcion", "").strip(),
        "tipo": request.POST.get("tipo", "").strip(),
        "tipo_beneficio": request.POST.get("tipo_beneficio", "").strip(),
        "valor": request.POST.get("valor", "").strip(),
        "fecha_inicio": request.POST.get("fecha_inicio", "").strip(),
        "fecha_fin": request.POST.get("fecha_fin", "").strip(),
        "activo": request.POST.get("activo", "").strip(),
    }

    errores = {}

    # Validar que el estado recibido sea explícito.
    estados_validos = {
        "true": True,
        "false": False,
    }

    estado_recibido = datos["activo"].lower()

    if estado_recibido not in estados_validos:
        errores["activo"] = [
            "Selecciona un estado válido para el descuento."
        ]

    # Convertir el valor a Decimal sin aceptar texto arbitrario.
    valor = None

    try:
        valor = Decimal(datos["valor"])

        if not valor.is_finite():
            raise InvalidOperation

    except (InvalidOperation, ValueError):
        errores["valor"] = [
            "Ingresa un valor numérico válido para el descuento."
        ]

    # Interpretar las fechas en formato YYYY-MM-DD.
    fecha_inicio = parse_date(datos["fecha_inicio"])
    fecha_fin = parse_date(datos["fecha_fin"])

    if fecha_inicio is None:
        errores["fecha_inicio"] = [
            "Ingresa una fecha de inicio válida."
        ]

    if fecha_fin is None:
        errores["fecha_fin"] = [
            "Ingresa una fecha de finalización válida."
        ]

    # Asignar únicamente los campos permitidos.
    instancia.nombre = datos["nombre"]
    instancia.descripcion = datos["descripcion"]
    instancia.tipo = datos["tipo"]
    instancia.tipo_beneficio = datos["tipo_beneficio"]

    if valor is not None:
        instancia.valor = valor

    if fecha_inicio is not None:
        instancia.fecha_inicio = fecha_inicio

    if fecha_fin is not None:
        instancia.fecha_fin = fecha_fin

    if estado_recibido in estados_validos:
        instancia.activo = estados_validos[estado_recibido]

    # full_clean ejecuta la validación de campos, choices,
    # validadores del modelo y el método clean().
    try:
        instancia.full_clean()
    except ValidationError as exc:
        if hasattr(exc, "message_dict"):
            for campo, mensajes in exc.message_dict.items():
                errores.setdefault(campo, []).extend(mensajes)
        else:
            errores.setdefault("__all__", []).extend(exc.messages)

    if errores:
        return None, datos, errores

    return instancia, datos, {}


# ==========================================================
# LISTAR DESCUENTOS
# ==========================================================

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_http_methods(["GET"])
def ver_descuentos(request):

    descuentos = Descuentos.objects.all().order_by(
        "-fecha_creacion",
        "nombre",
    )

    return render(
        request,
        "descuentos/listar_descuentos.html",
        {"datos": descuentos},
    )


# ==========================================================
# CREAR DESCUENTO
# ==========================================================

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_http_methods(["GET", "POST"])
def crear_descuento(request):

    if request.method == "POST":
        descuento, datos, errores = _guardar_datos_descuento(request)

        if not errores:
            try:
                with transaction.atomic():
                    descuento.save()

                messages.success(
                    request,
                    f"Descuento '{descuento.nombre}' creado correctamente.",
                )
                return redirect("agenda:ver_descuentos")

            except DatabaseError:
                messages.error(
                    request,
                    "Ocurrió un error al guardar el descuento.",
                )
        else:
            messages.error(
                request,
                "Revisa los campos señalados antes de continuar.",
            )

        return render(
            request,
            "descuentos/formulario_descuentos.html",
            {
                "datos": datos,
                "errores": errores,
                "modo_edicion": False,
            },
        )

    return render(
        request,
        "descuentos/formulario_descuentos.html",
        {
            "datos": {
                "tipo": Descuentos.Tipo.PERSONALIZADO,
                "tipo_beneficio": Descuentos.TipoBeneficio.PORCENTAJE,
                "activo": "true",
            },
            "errores": {},
            "modo_edicion": False,
        },
    )


# ==========================================================
# ACTUALIZAR DESCUENTO
# ==========================================================

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_http_methods(["GET", "POST"])
def actualizar_descuento(request, id):

    descuento = get_object_or_404(Descuentos, pk=id)

    if request.method == "POST":
        instancia, datos, errores = _guardar_datos_descuento(
            request,
            descuento=descuento,
        )

        if not errores:
            try:
                with transaction.atomic():
                    instancia.save()

                messages.success(
                    request,
                    f"Descuento '{instancia.nombre}' actualizado correctamente.",
                )
                return redirect("agenda:ver_descuentos")

            except DatabaseError:
                messages.error(
                    request,
                    "Ocurrió un error al actualizar el descuento.",
                )
        else:
            messages.error(
                request,
                "Revisa los campos señalados antes de continuar.",
            )

        return render(
            request,
            "descuentos/formulario_descuentos.html",
            {
                "datos": datos,
                "errores": errores,
                "modo_edicion": True,
            },
        )

    return render(
        request,
        "descuentos/formulario_descuentos.html",
        {
            "datos": descuento,
            "errores": {},
            "modo_edicion": True,
        },
    )


# ==========================================================
# DESACTIVAR DESCUENTO
# ==========================================================

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_POST
def eliminar_descuento(request, id):

    try:
        with transaction.atomic():
            descuento = get_object_or_404(
                Descuentos.objects.select_for_update(),
                pk=id,
            )

            if not descuento.activo:
                messages.warning(
                    request,
                    "Este descuento ya se encuentra inactivo.",
                )
                return redirect("agenda:ver_descuentos")

            nombre = descuento.nombre
            descuento.activo = False
            descuento.save(
                update_fields=["activo", "fecha_actualizacion"]
            )

        messages.success(
            request,
            f"El descuento '{nombre}' fue desactivado correctamente.",
        )

    except DatabaseError:
        messages.error(
            request,
            "Ocurrió un error al desactivar el descuento.",
        )

    return redirect("agenda:ver_descuentos")


@login_required(login_url="agenda:login")
def busqueda_global(request):
    termino = request.GET.get("q", "").strip()

    resultados = []
    accesos = []

    # Obtener el rol del usuario autenticado
    try:
        perfil = PerfilUsuario.objects.select_related("rol").get(
            user=request.user
        )
        rol = perfil.rol.nombre.upper() if perfil.rol else ""
    except PerfilUsuario.DoesNotExist:
        rol = ""

    # No realizar búsquedas vacías
    if not termino:
        return render(
            request,
            "busqueda_global.html",
            {
                "termino": termino,
                "resultados": resultados,
                "accesos": accesos,
            },
        )

    # -----------------------------------------
    # ACCESOS SEGÚN EL ROL DEL USUARIO
    # -----------------------------------------

    accesos_comunes = [
        {
            "nombre": "Servicios",
            "url": reverse("agenda:lista_servicios"),
            "descripcion": "Consultar servicios disponibles",
        },
        {
            "nombre": "Ajustes",
            "url": reverse("agenda:ajustes"),
            "descripcion": "Configurar tu perfil y preferencias",
        },
        {
            "nombre": "Soporte",
            "url": reverse("agenda:soporte"),
            "descripcion": "Consultar o solicitar ayuda",
        },
    ]

    accesos_disponibles = []

    if rol == "CLIENTE":
        accesos_disponibles = accesos_comunes + [
            {
                "nombre": "Mis citas",
                "url": reverse("agenda:mis_citas"),
                "descripcion": "Consultar tus citas agendadas",
            },
            {
                "nombre": "Mis reseñas",
                "url": reverse("agenda:mis_resenas"),
                "descripcion": "Consultar tus reseñas",
            },
        ]

        # Buscar únicamente las citas del cliente autenticado
        citas = Citas.objects.filter(
            cliente__user=request.user
        ).filter(
            Q(servicios__nombre__icontains=termino)
            | Q(manicurista__nombre__icontains=termino)
            | Q(manicurista__apellido__icontains=termino)
            | Q(estado__icontains=termino)
        ).distinct()

        for cita in citas:
            resultados.append({
                "tipo": "Cita",
                "titulo": f"Cita de {cita.servicios.nombre}",
                "descripcion": (
                    f"Manicurista: {cita.manicurista.nombre} "
                    f"{cita.manicurista.apellido} | "
                    f"Fecha: {cita.fecha} | Estado: {cita.estado}"
                ),
                "url": reverse("agenda:mis_citas"),
            })

        # Buscar servicios que el cliente puede consultar
        servicios = Servicios.objects.filter(
            Q(nombre__icontains=termino)
            | Q(descripcion__icontains=termino)
        )

        for servicio in servicios:
            resultados.append({
                "tipo": "Servicio",
                "titulo": servicio.nombre,
                "descripcion": servicio.descripcion,
                "url": reverse("agenda:lista_servicios"),
            })

    elif rol == "MANICURISTA":
        accesos_disponibles = accesos_comunes + [
            {
                "nombre": "Citas asignadas",
                "url": reverse("agenda:citas_asignadas"),
                "descripcion": "Consultar las citas asignadas",
            },
            {
                "nombre": "Calendario",
                "url": reverse("agenda:ver_calendario"),
                "descripcion": "Consultar tu calendario",
            },
        ]

        # Buscar únicamente las citas de la manicurista autenticada
        citas = Citas.objects.filter(
            manicurista__user=request.user
        ).filter(
            Q(cliente__nombre__icontains=termino)
            | Q(cliente__apellido__icontains=termino)
            | Q(servicios__nombre__icontains=termino)
            | Q(estado__icontains=termino)
        ).distinct()

        for cita in citas:
            resultados.append({
                "tipo": "Cita asignada",
                "titulo": f"Cita de {cita.cliente.nombre} {cita.cliente.apellido}",
                "descripcion": (
                    f"Servicio: {cita.servicios.nombre} | "
                    f"Fecha: {cita.fecha} | Estado: {cita.estado}"
                ),
                "url": reverse("agenda:citas_asignadas"),
            })

        servicios = Servicios.objects.filter(
            Q(nombre__icontains=termino)
            | Q(descripcion__icontains=termino)
        )

        for servicio in servicios:
            resultados.append({
                "tipo": "Servicio",
                "titulo": servicio.nombre,
                "descripcion": servicio.descripcion,
                "url": reverse("agenda:lista_servicios"),
            })

    elif rol == "ADMINISTRADOR":
        accesos_disponibles = accesos_comunes + [
            {
                "nombre": "Clientes",
                "url": reverse("agenda:ver_cliente"),
                "descripcion": "Administrar clientes",
            },
            {
                "nombre": "Manicuristas",
                "url": reverse("agenda:ver_manicuristas"),
                "descripcion": "Administrar manicuristas",
            },
            {
                "nombre": "Todas las citas",
                "url": reverse("agenda:ver_todas_citas"),
                "descripcion": "Consultar y gestionar citas",
            },
            {
                "nombre": "Inventario",
                "url": reverse("agenda:ver_inventario"),
                "descripcion": "Controlar los insumos del spa",
            },
            {
                "nombre": "Pagos",
                "url": reverse("agenda:ver_pagos"),
                "descripcion": "Consultar pagos",
            },
            {
                "nombre": "Gastos",
                "url": reverse("agenda:ver_gasto"),
                "descripcion": "Consultar gastos",
            },
            {
                "nombre": "Soporte administrativo",
                "url": reverse("agenda:soporte_administrador"),
                "descripcion": "Gestionar solicitudes de soporte",
            },
            {
                "nombre": "Mensajes de contacto",
                "url": reverse("agenda:ver_mensajes_contacto"),
                "descripcion": "Ver mensajes enviados desde la página principal",
            },
        ]

        # Clientes
        clientes = Clientes.objects.filter(
            Q(nombre__icontains=termino)
            | Q(apellido__icontains=termino)
            | Q(telefono__icontains=termino)
            | Q(email__icontains=termino)
        )

        for cliente in clientes:
            resultados.append({
                "tipo": "Cliente",
                "titulo": f"{cliente.nombre} {cliente.apellido}",
                "descripcion": (
                    f"Teléfono: {cliente.telefono} | "
                    f"Correo: {cliente.email}"
                ),
                "url": reverse("agenda:ver_cliente"),
            })

        # Manicuristas
        manicuristas = Manicurista.objects.filter(
            Q(nombre__icontains=termino)
            | Q(apellido__icontains=termino)
            | Q(especialidad__icontains=termino)
            | Q(email__icontains=termino)
        )

        for manicurista in manicuristas:
            resultados.append({
                "tipo": "Manicurista",
                "titulo": f"{manicurista.nombre} {manicurista.apellido}",
                "descripcion": (
                    f"Especialidad: {manicurista.especialidad}"
                ),
                "url": reverse("agenda:ver_manicuristas"),
            })

        # Todas las citas
        citas = Citas.objects.filter(
            Q(cliente__nombre__icontains=termino)
            | Q(cliente__apellido__icontains=termino)
            | Q(manicurista__nombre__icontains=termino)
            | Q(manicurista__apellido__icontains=termino)
            | Q(servicios__nombre__icontains=termino)
            | Q(estado__icontains=termino)
        ).distinct()

        for cita in citas:
            resultados.append({
                "tipo": "Cita",
                "titulo": (
                    f"{cita.cliente.nombre} {cita.cliente.apellido}"
                    f" — {cita.servicios.nombre}"
                ),
                "descripcion": (
                    f"Manicurista: {cita.manicurista.nombre} "
                    f"{cita.manicurista.apellido} | "
                    f"Fecha: {cita.fecha} | Estado: {cita.estado}"
                ),
                "url": reverse("agenda:ver_todas_citas"),
            })

        # Servicios
        servicios = Servicios.objects.filter(
            Q(nombre__icontains=termino)
            | Q(descripcion__icontains=termino)
        )

        for servicio in servicios:
            resultados.append({
                "tipo": "Servicio",
                "titulo": servicio.nombre,
                "descripcion": servicio.descripcion,
                "url": reverse("agenda:ver_servicio"),
            })

        # Inventario
        inventario = Inventario.objects.filter(
            Q(nombre__icontains=termino)
            | Q(categoria__icontains=termino)
        )

        for producto in inventario:
            resultados.append({
                "tipo": "Inventario",
                "titulo": producto.nombre,
                "descripcion": (
                    f"Categoría: {producto.categoria} | "
                    f"Cantidad: {producto.cantidad}"
                ),
                "url": reverse("agenda:ver_inventario"),
            })

        # Pagos
        pagos = Pagos.objects.filter(
            Q(estado__icontains=termino)
            | Q(metodo_pago__icontains=termino)
        ).distinct()

        for pago in pagos:
            resultados.append({
                "tipo": "Pago",
                "titulo": f"Pago #{pago.pk}",
                "descripcion": (
                    f"Estado: {pago.estado} | "
                    f"Valor: {pago.valor}"
                ),
                "url": reverse("agenda:ver_pagos"),
            })

        # Gastos
        gastos = Gastos.objects.filter(
            Q(concepto__icontains=termino)
        )

        for gasto in gastos:
            resultados.append({
                "tipo": "Gasto",
                "titulo": gasto.concepto,
                "descripcion": f"Valor: {gasto.valor}",
                "url": reverse("agenda:ver_gasto"),
            })

        # Solicitudes de soporte
        solicitudes = SolicitudSoporte.objects.filter(
            Q(nombre_solicitante__icontains=termino)
            | Q(asunto__icontains=termino)
            | Q(descripcion__icontains=termino)
            | Q(estado__icontains=termino)
        )

        for solicitud in solicitudes:
            resultados.append({
                "tipo": "Soporte",
                "titulo": solicitud.asunto,
                "descripcion": (
                    f"Solicitante: {solicitud.nombre_solicitante} | "
                    f"Estado: {solicitud.estado}"
                ),
                "url": reverse("agenda:soporte_administrador"),
            })

    else:
        accesos_disponibles = []

    # Filtrar los accesos según el término de búsqueda para que solo aparezcan los relacionados
    termino_lower = termino.lower()
    accesos = [
        acc for acc in accesos_disponibles 
        if termino_lower in acc["nombre"].lower() or termino_lower in acc["descripcion"].lower()
    ]

    return render(
        request,
        "busqueda_global.html",
        {
            "termino": termino,
            "resultados": resultados,
            "accesos": accesos,
        },
    )

@login_required(login_url="agenda:login")
def ver_mensajes_contacto(request):
    # Validar que sea administrador
    try:
        perfil = PerfilUsuario.objects.select_related("rol").get(user=request.user)
        rol = perfil.rol.nombre.upper() if perfil.rol else ""
    except PerfilUsuario.DoesNotExist:
        rol = ""

    if rol != "ADMINISTRADOR":
        return redirect("agenda:dashboard")

    mensajes = MensajeContacto.objects.all().order_by("-fecha")

    return render(request, "mensajes_contacto.html", {
        "mensajes": mensajes
    })

@login_required(login_url="agenda:login")
def responder_mensaje_contacto(request, mensaje_id):
    # Validar que sea administrador
    try:
        perfil = PerfilUsuario.objects.select_related("rol").get(
            user=request.user
        )
        rol = perfil.rol.nombre.upper() if perfil.rol else ""
    except PerfilUsuario.DoesNotExist:
        rol = ""

    if rol != "ADMINISTRADOR":
        return redirect("agenda:dashboard")

    mensaje = get_object_or_404(MensajeContacto, pk=mensaje_id)

    if request.method == "POST":
        respuesta = request.POST.get("respuesta", "").strip()

        if not respuesta:
            messages.error(request, "Escribe una respuesta antes de enviarla.")
            return render(
                request,
                "responder_mensaje_contacto.html",
                {"mensaje": mensaje}
            )

        try:
            enviados = send_mail(
                subject=f"Respuesta a tu consulta en Spa Deseo: {mensaje.asunto}",
                message=(
                    f"Hola {mensaje.nombre},\n\n"
                    f"{respuesta}\n\n"
                    "Cordialmente,\n"
                    "Equipo Spa Deseo"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[mensaje.correo],
                fail_silently=False,
            )

            if enviados == 1:
                mensaje.respondido = True
                mensaje.save(update_fields=["respondido"])

                messages.success(
                    request,
                    f"La respuesta fue enviada a {mensaje.correo}."
                )
                return redirect("agenda:ver_mensajes_contacto")

            messages.error(
                request,
                "No se pudo confirmar el envío del correo."
            )

        except Exception:
            # Registrar el detalle en los logs del servidor.
            import logging
            logging.getLogger(__name__).exception(
                "Error al enviar una respuesta de contacto"
            )
            messages.error(
                request,
                "No se pudo enviar el correo. Revisa la configuración SMTP."
            )

    return render(
        request,
        "responder_mensaje_contacto.html",
        {"mensaje": mensaje}
    )