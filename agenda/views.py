import os
import re
import json
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime, date, time, timedelta

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

# Django REST Framework & Spectacular
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from drf_spectacular.utils import extend_schema

# Importaciones locales explícitas
from .models import (
    Citas, Clientes, Manicurista, Servicios, Inventario, Pagos, Recibo, Gastos, Resena
)
from .serializador import (
    ClientesSerializer, ManicuristaSerializer, ServiciosSerializer,
    CitasSerializer, InventarioSerializer, PagosSerializer,
    ReciboSerializer, GastosSerializer
)
from .permissions import TieneRolDB, IsStaffOrReadOnly, EsAdministrador
from .utils import validar_password, requiere_rol

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
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated, TieneRolDB]


    queryset = Clientes.objects.all()
    serializer_class = ClientesSerializer


class ManicuristaViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]


    queryset = Manicurista.objects.all()
    serializer_class = ManicuristaSerializer


class ServiciosViewSet(viewsets.ModelViewSet):
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
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated, TieneRolDB]
    queryset = Citas.objects.all()
    serializer_class = CitasSerializer

    @extend_schema(
        summary="Lista de todas las citas"
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

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


def ajustes(request):
    return render(request, 'ajustes.html')

def soporte(request):
    return render(request, 'soporte.html')


def index(request):
    return render(request, "index.html")

@login_required(login_url="agenda:login")
@requiere_rol("MANICURISTA")
def citas_asignadas(request):
    """
    Muestra el listado de citas asignadas a la manicurista autenticada.
    Incluye optimización de consultas SQL (Anti N+1) y control estricto de perfil.
    """
    # 1. Validación de perfil asignado
    try:
        manicurista = Manicurista.objects.get(user=request.user)
    except Manicurista.DoesNotExist:
        messages.error(request, "Tu usuario no está vinculado a un perfil activo de manicurista.")
        return redirect("agenda:login")

    # 2. Consulta optimizada con JOINs explícitos y ordenamiento cronológico
    citas = Citas.objects.filter(manicurista=manicurista)\
                         .select_related('cliente', 'servicios')\
                         .order_by('-fecha', '-hora')

    contexto = {
        "manicurista": manicurista,
        "citas": citas,
    }

    return render(request, "manicurista/citas_asignadas.html", contexto)



@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE", "MANICURISTA","ADMINISTRADOR")
@transaction.atomic
def editar_perfil(request):
    """
    Edición de perfil unificada para Cliente y Manicurista.
    """
    usuario = request.user
    
    try:
        rol = usuario.perfil.rol.nombre.upper()
    except (AttributeError, PerfilUsuario.DoesNotExist):
        messages.error(request, "Error de autenticación: El usuario no posee un rol válido.")
        return redirect("agenda:login")

    # 1. Obtener perfil según el rol
    if rol == "CLIENTE":
        perfil = get_object_or_404(Clientes, user=usuario)
    elif rol == "MANICURISTA":
        perfil = get_object_or_404(Manicurista, user=usuario)
    
    elif rol == "ADMINISTRADOR":
        perfil = get_object_or_404(Administrador, user=usuario)
    else:
        messages.error(request, "No tienes permisos para editar este perfil.")
        return redirect("agenda:dashboard")

    if request.method == "POST":
        nuevo_email = request.POST.get("email", "").strip()
        nuevo_nombre = request.POST.get("nombre", "").strip()
        nuevo_apellido = request.POST.get("apellido", "").strip()
        nuevo_telefono = request.POST.get("telefono", "").strip()

        # 2. Control de Seguridad: Validar unicidad de Email
        if nuevo_email and nuevo_email.lower() != usuario.email.lower():
            if User.objects.filter(email__iexact=nuevo_email).exclude(pk=usuario.pk).exists():
                messages.error(request, "El correo electrónico ingresado ya está registrado por otro usuario.")
                return redirect("agenda:editar_perfil")

        # 3. Control de Seguridad: Manejo de Foto (Eliminar o Actualizar)
        eliminar_foto = request.POST.get("eliminar_foto") == "true"
        foto = request.FILES.get("foto_perfil")

        if eliminar_foto:
            if perfil.foto_perfil:
                perfil.foto_perfil.delete(save=False)
            perfil.foto_perfil = None
        elif foto:
            ext = os.path.splitext(foto.name)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                messages.error(request, "Formato de imagen no permitido. Usa JPG, PNG o WEBP.")
                return redirect("agenda:editar_perfil")
            
            if perfil.foto_perfil:
                perfil.foto_perfil.delete(save=False)
            perfil.foto_perfil = foto

        # 4. Actualización en lote (Consistencia en DB)
        try:
            perfil.nombre = nuevo_nombre
            perfil.apellido = nuevo_apellido
            perfil.telefono = nuevo_telefono
            perfil.email = nuevo_email
            perfil.save()

            usuario.first_name = nuevo_nombre
            usuario.last_name = nuevo_apellido
            usuario.email = nuevo_email
            usuario.username = nuevo_email 
            usuario.save()

            # Actualizar la sesión para que el header refleje los cambios al instante
            if 'logueado' in request.session:
                request.session['logueado']['nombre'] = nuevo_nombre
                request.session['logueado']['apellido'] = nuevo_apellido
                request.session.modified = True

            messages.success(request, "Perfil actualizado correctamente.")
            return redirect("agenda:editar_perfil")

        except IntegrityError:
            messages.error(request, "Error al guardar los datos. Intenta nuevamente.")
            return redirect("agenda:editar_perfil")

    # >>> ESTO ES LO QUE FALTABA O FALLABA EN LAS PETICIONES GET <<<
    contexto = {
        "usuario": usuario,
        "perfil": perfil,
        "rol": rol,
    }

    return render(request, "cliente/editar_perfil.html", contexto)




def login(request):
    # Si el usuario ya está logueado, lo mandamos al dashboard
    if request.user.is_authenticated:
        return redirect("agenda:dashboard")

    if request.method == "POST":

        # El formulario envía el correo en el campo "user"
        correo = request.POST.get("user", "").strip()
        clave = request.POST.get("password", "")

        if not correo or not clave:
            messages.error(
                request,
                "Debes ingresar el correo y la contraseña."
            )
            return redirect("agenda:login")

        # Buscar el usuario por correo
        try:
            usuario = User.objects.get(email__iexact=correo)
        except User.DoesNotExist:
            messages.error(
                request,
                "Credenciales inválidas"
            )
            return redirect("agenda:login")

        # Autenticar utilizando el username real de Django
        user = authenticate(
            request,
            username=usuario.username,
            password=clave
        )

        if user is None:
            messages.error(
                request,
                "Credenciales inválidas"
            )
            return redirect("agenda:login")

        # Verificar si la cuenta está activa
        if not user.is_active:
            messages.error(
                request,
                "Tu cuenta está desactivada."
            )
            return redirect("agenda:login")

        # Verificar que tenga perfil
        try:
            perfil = user.perfil
        except (AttributeError, PerfilUsuario.DoesNotExist):
            messages.error(
                request,
                "El usuario no tiene un perfil asignado."
            )
            return redirect("agenda:login")

        # Verificar que tenga rol
        if not perfil.rol:
            messages.error(
                request,
                "El usuario no tiene un rol asignado."
            )
            return redirect("agenda:login")

        rol = perfil.rol.nombre.capitalize()

        # Iniciar sesión con Django
        auth_login(request, user)

        # Crear sesión compatible con el sistema anterior
        request.session["logueado"] = {
            "id": user.id,
            "nombre": user.first_name or user.username,
            "apellido": user.last_name or "",
            "rol": rol,
            "email": user.email,
        }

        request.session.modified = True

        return redirect("agenda:dashboard")

    return render(request, "login.html")


@transaction.atomic
def register(request):

    # Redireccionar si el usuario ya está autenticado
    if request.user.is_authenticated:
        return redirect("agenda:dashboard")

    if request.method == "POST":

        password = request.POST.get("password")
        email = request.POST.get("email", "").strip()
        nombre = request.POST.get("nombre", "").strip()
        apellido = request.POST.get("apellido", "").strip()
        telefono = request.POST.get("telefono", "").strip()

        # Validar contraseña
        error = validar_password(password)

        if error:
            messages.error(request, error)
            return redirect("agenda:register")

        # Verificar correo (Evita duplicados por mayúsculas/minúsculas)
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            messages.error(
                request,
                "Ya existe una cuenta con ese correo."
            )
            return redirect("agenda:register")

        try:

            # 1. Buscar el rol CLIENTE
            rol = Rol.objects.get(nombre="CLIENTE")

            # 2. Crear usuario Django
            user = User(
                username=email,
                email=email,
                first_name=nombre,
                last_name=apellido
            )

            # 3. Guardar contraseña de forma segura
            user.set_password(password)
            user.save()

            # 4. La señal crea automáticamente el PerfilUsuario.
            #    Aquí solamente le asignamos el rol.
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
                "Cuenta creada correctamente. Ahora puedes iniciar sesión."
            )

            return redirect("agenda:login")

        except Rol.DoesNotExist:

            messages.error(
                request,
                "El rol CLIENTE no existe en la base de datos."
            )

            return redirect("agenda:register")

        except Exception:

            # Mensaje seguro para el usuario (sin exponer detalles técnicos de la BD)
            messages.error(
                request,
                "Ocurrió un error al crear la cuenta. Inténtalo de nuevo."
            )

            return redirect("agenda:register")

    return render(request, "register.html")



@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE", "MANICURISTA", "ADMINISTRADOR")
def dashboard(request):

    try:
        rol = request.user.perfil.rol.nombre.upper()
    except (AttributeError, PerfilUsuario.DoesNotExist):
        messages.error(request, "Tu usuario no tiene un rol asignado.")
        return redirect("agenda:login")

    citas = Citas.objects.none()
    cliente_id_logueado = None
    manicurista_logueada = None

    # 1. Filtro dinámico de Citas según el Rol del usuario logueado
    if rol == "CLIENTE":
        try:
            cliente = Clientes.objects.get(user=request.user)
            cliente_id_logueado = cliente.id
            citas = Citas.objects.filter(
                cliente=cliente
            ).select_related('manicurista', 'servicios').order_by('-fecha', '-hora')[:5]
        except Clientes.DoesNotExist:
            messages.error(request, "No existe información de cliente asociada a tu usuario.")
            return redirect("agenda:login")

    elif rol == "MANICURISTA":
        try:
            manicurista_logueada = Manicurista.objects.get(user=request.user)
            citas = Citas.objects.filter(
                manicurista=manicurista_logueada
            ).select_related('cliente', 'servicios').order_by('-fecha', '-hora')[:5]
        except Manicurista.DoesNotExist:
            messages.error(request, "No existe información de manicurista asociada a tu usuario.")
            return redirect("agenda:login")

    elif rol == "ADMINISTRADOR":
        # El administrador puede visualizar el panorama general de citas recientes
        citas = Citas.objects.select_related('cliente', 'manicurista', 'servicios').order_by('-fecha', '-hora')[:10]

    # 2. Catálogos globales de apoyo
    servicios_disponibles = Servicios.objects.filter(estado="Activo")[:6]
    manicuristas_disponibles = Manicurista.objects.filter(estado="Activa")[:6]

    contexto = {
        "usuario": request.user.get_full_name() or request.user.username,
        "rol": rol,
        "citas": citas,
        "servicios": servicios_disponibles,
        "manicuristas": manicuristas_disponibles,
        "cliente_id_logueado": cliente_id_logueado,
    }

    return render(request, "dashboard_copy.html", contexto)


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
@requiere_rol("ADMINISTRADOR", "MANICURISTA")  # <--- CLIENTE removido por protección de datos (Privacy / Anti-Scraping)
def ver_cliente(request):

    # Consulta optimizada con select_related para traer la información en 1 sola query
    c = Clientes.objects.filter(
        user__perfil__rol__nombre="CLIENTE"
    ).select_related('user').order_by('nombre')

    contexto = {
        "datos": c
    }

    return render(request, "cliente/clientes.html", contexto)

@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
def crear_cliente(request):
    if request.method == "POST":
        password = request.POST.get("password")
        email = request.POST.get("email", "").strip()
        nombre = request.POST.get("nombre", "").strip()
        apellido = request.POST.get("apellido", "").strip()
        telefono = request.POST.get("telefono", "").strip()

        error = validar_password(password)

        if error:
            messages.error(request, error)
            return redirect("agenda:crear_cliente")

        # Verificar que el correo no esté registrado (insensible a mayúsculas)
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            messages.error(
                request,
                "Ya existe un usuario registrado con ese correo."
            )
            return redirect("agenda:crear_cliente")

        try:
            with transaction.atomic():

                # 1. Buscar el rol CLIENTE
                rol = Rol.objects.get(nombre="CLIENTE")

                # 2. Crear usuario de Django
                user = User(
                    username=email,
                    email=email,
                    first_name=nombre,
                    last_name=apellido
                )

                # 3. Guardar contraseña de forma segura
                user.set_password(password)
                user.save()

                # 4. Asignar rol al Perfil creado por la señal
                perfil, _ = PerfilUsuario.objects.get_or_create(user=user)
                perfil.rol = rol
                perfil.save()

                # 5. Crear la ficha del cliente
                Clientes.objects.create(
                    user=user,
                    nombre=nombre,
                    apellido=apellido,
                    telefono=telefono,
                    email=email
                )

            messages.success(request, "Cliente creado correctamente.")
            return redirect("agenda:ver_cliente")

        except Rol.DoesNotExist:
            messages.error(request, "El rol CLIENTE no existe. Créalo primero.")
            return redirect("agenda:crear_cliente")

        except Exception:
            messages.error(request, "Ocurrió un error al crear el cliente. Inténtalo de nuevo.")
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
        messages.error(request, "No existe información de cliente asociada a tu usuario.")
        return redirect("agenda:login")

    # 2. Consultar reseñas con JOINs optimizados para la plantilla
    resenas = Resena.objects.filter(
        cita__cliente=cliente
    ).select_related(
        'cita',
        'cita__manicurista',
        'cita__servicios'
    ).order_by(
        '-cita__fecha',
        '-cita__hora'
    )

    return render(request, 'cliente/mis_resenas.html', {
        'resenas': resenas
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

#CRUD CITAS
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

    return render(request, "cliente/mis_citas.html", {
        "citas": citas
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


@requiere_rol("ADMINISTRADOR")
def ver_todas_citas(request):
    try:
        # Robustez: Consulta segura de todas las citas ordenadas de forma descendente por fecha y hora
        citas = Citas.objects.all().order_by('-fecha', '-hora')
    except DatabaseError:
        # Control específico ante fallos de base de datos
        citas = []
        messages.error(request, "Ocurrió un error en la base de datos al intentar cargar las citas.")
    except Exception:
        # Control genérico ante cualquier eventualidad imprevista
        citas = []
        messages.error(request, "Ocurrió un error inesperado al cargar las citas.")

    contexto = {
        "citas": citas
    }
    return render(request, "administrador/todas_citas.html", contexto)

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
                ).exclude(estado="Cancelada")

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

                # 10. Persistencia
                Citas.objects.create(
                    cliente=cliente,
                    manicurista=manicurista,
                    servicios=servicio,
                    fecha=fecha_obj,
                    hora=hora_obj,
                    total=servicio.precio,
                    estado="programada"
                )

            messages.success(request, "Cita agendada correctamente.")
            return redirect("agenda:mis_citas")

        except Exception:
            messages.error(request, "Ocurrió un problema al agendar la cita. Inténtalo de nuevo.")
            return redirect("agenda:crear_citas")

    # GET
    manicurista = Manicurista.objects.filter(estado="Activa")
    servicios = Servicios.objects.filter(estado__iexact="Activo")

    return render(request, "cliente/crear_cita.html", {
        "cliente": cliente,
        "manicurista": manicurista,
        "servicios": servicios
    })


@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE") # <-- Asegúrate de incluir ADMINISTRADOR aquí
@require_http_methods(["GET", "POST"])
@transaction.atomic
def eliminar_citas(request, id):
    try:
        # Si es un administrador, puede ver y cancelar cualquier cita sin la restricción del cliente dueño
        if request.user.perfil.rol.nombre.upper() == "ADMINISTRADOR":
            cita = get_object_or_404(Citas, pk=id)
        else:
            # Si es un cliente, validamos que sea estrictamente el dueño de la cita
            cliente = get_object_or_404(Clientes, user=request.user)
            cita = get_object_or_404(Citas, pk=id, cliente=cliente)

        # Validaciones de estado
        if cita.estado == "Cancelada":
            messages.warning(request, "Esta cita ya se encuentra cancelada.")
            return redirect("agenda:citas_asignadas" if request.user.perfil.rol.nombre.upper() == "ADMINISTRADOR" else "agenda:mis_citas")

        if cita.estado == "Completada":
            messages.error(request, "No puedes cancelar una cita que ya ha sido completada.")
            return redirect("agenda:citas_asignadas" if request.user.perfil.rol.nombre.upper() == "ADMINISTRADOR" else "agenda:mis_citas")

        # Cancelación lógica
        cita.estado = "Cancelada"
        cita.save()

        messages.success(request, "La cita se ha cancelado correctamente y el horario ha sido liberado.")

    except Exception as e:
        messages.error(request, "Ocurrió un error inesperado al procesar la cancelación.")

    # Redirección dinámica según quién realice la acción
    if request.user.perfil.rol.nombre.upper() == "ADMINISTRADOR":
        return redirect("agenda:dashboard") # O la lista de citas del admin
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

            messages.success(request, "Cita actualizada correctamente.")
            return redirect("agenda:mis_citas")

        except Exception:
            messages.error(request, "Ocurrió un error inesperado al actualizar la cita.")
            return redirect("agenda:actualizar_citas", id=id)

    # PETICIÓN GET
    manicurista = Manicurista.objects.filter(estado="Activa")
    servicios = Servicios.objects.filter(estado="Activo")

    contexto = {
        "cita": cita,
        "cliente": cliente,
        "manicurista": manicurista,
        "servicios": servicios
    }

    return render(request, "cliente/actualizar_citas.html", contexto)

import re
from datetime import datetime, date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
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


# 2. CREAR MANICURISTA
@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_http_methods(["GET", "POST"])
def crear_manicurista(request):
    if request.method == "POST":
        password = request.POST.get("password")
        email = request.POST.get("email", "").strip().lower()
        nombre = request.POST.get("nombre", "").strip()
        apellido = request.POST.get("apellido", "").strip()
        telefono = request.POST.get("telefono", "").strip()
        especialidad = request.POST.get("especialidad", "").strip()
        fecha_ingreso_raw = request.POST.get("fecha_ingreso")
        foto_perfil = request.FILES.get("foto_perfil")

        form_data = {
            "nombre": nombre,
            "apellido": apellido,
            "email": email,
            "telefono": telefono,
            "especialidad": especialidad,
            "fecha_ingreso": fecha_ingreso_raw
        }

        # Validar campos obligatorios
        if not all([nombre, apellido, email, password, telefono, especialidad, fecha_ingreso_raw]):
            messages.error(request, "Todos los campos obligatorios deben diligenciarse.")
            return render(request, "manicurista/crear_manicurista.html", {"form_data": form_data})

        # Validar contraseña
        error_pass = validar_password(password)
        if error_pass:
            messages.error(request, error_pass)
            return render(request, "manicurista/crear_manicurista.html", {"form_data": form_data})

        # Validar formato del correo
        patron_email = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(patron_email, email):
            messages.error(request, "El correo electrónico no tiene un formato válido.")
            return render(request, "manicurista/crear_manicurista.html", {"form_data": form_data})

        # Validar Unicidad de Correo y Username
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            messages.error(request, "Ya existe un usuario o manicurista registrada con ese correo.")
            return render(request, "manicurista/crear_manicurista.html", {"form_data": form_data})

        # Validar teléfono
        if not re.match(r"^\+?\d{7,15}$", telefono):
            messages.error(request, "El número de teléfono ingresado no es válido.")
            return render(request, "manicurista/crear_manicurista.html", {"form_data": form_data})

        # Validar fecha de ingreso
        try:
            fecha_ingreso = datetime.strptime(fecha_ingreso_raw, "%Y-%m-%d").date()
            if fecha_ingreso > date.today():
                messages.error(request, "La fecha de ingreso no puede ser una fecha futura.")
                return render(request, "manicurista/crear_manicurista.html", {"form_data": form_data})
        except ValueError:
            messages.error(request, "La fecha de ingreso no tiene un formato válido.")
            return render(request, "manicurista/crear_manicurista.html", {"form_data": form_data})

        # Persistencia Atómica
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=nombre,
                    last_name=apellido
                )

                rol, _ = Rol.objects.get_or_create(nombre="MANICURISTA")

                PerfilUsuario.objects.create(
                    user=user,
                    rol=rol
                )

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
                    foto_perfil=foto_perfil
                )

            messages.success(request, f"Manicurista '{nombre} {apellido}' registrada correctamente.")
            return redirect("agenda:ver_manicuristas")

        except IntegrityError:
            messages.error(request, "Ocurrió un conflicto de integridad al guardar la manicurista.")
        except Exception as e:
            print(f"Error inesperado al crear: {e}")
            messages.error(request, "Ocurrió un error inesperado al crear la manicurista.")

        return render(request, "manicurista/crear_manicurista.html", {"form_data": form_data})

    return render(request, "manicurista/crear_manicurista.html")


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
            estado__in=["Cancelada", "Completada"]
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


@require_http_methods(["GET", "POST"])
@requiere_rol("MANICURISTA")
def cambiar_estado_cita(request, cita_id, nuevo_estado):
    # Control de seguridad: Validar que el ID sea válido o exista antes de procesar
    if not cita_id:
        messages.error(request, "Identificador de cita no válido.")
        return redirect('agenda:citas_asignadas')

    try:
        # Obtenemos la manicurista usando 'user=request.user' tal como indican las opciones del modelo
        manicurista_actual = Manicurista.objects.get(user=request.user)
    except Manicurista.DoesNotExist:
        messages.error(request, "No se encontró un perfil de manicurista asociado a tu usuario.")
        return redirect('agenda:citas_asignadas')

    # Seguridad: Obtener la cita asegurando que pertenezca a la manicurista en sesión
    cita = get_object_or_404(Citas, id=cita_id, manicurista=manicurista_actual)
    
    # Validar que el nuevo estado sea válido dentro de las opciones del modelo
    estados_validos = dict(Citas.ESTADOS_CITA)
    
    if nuevo_estado not in estados_validos:
        messages.error(request, "El estado seleccionado no es válido.")
        return redirect('agenda:citas_asignadas')

    # Control de negocio adicional: Evitar reescribir el mismo estado innecesariamente
    if cita.estado == nuevo_estado:
        messages.warning(request, f"La cita ya se encuentra en estado '{estados_validos[nuevo_estado]}'.")
        return redirect('agenda:citas_asignadas')

    try:
        # Robustez: Usar transacción atómica para asegurar la integridad en base de datos
        with transaction.atomic():
            cita.estado = nuevo_estado
            cita.save()
            messages.success(request, f"Estado actualizado exitosamente a '{estados_validos[nuevo_estado]}'.")
            
    except Exception as e:
        # Control de errores y excepciones inesperadas
        messages.error(request, "Ocurrió un error interno al intentar actualizar el estado de la cita.")
        
    return redirect('agenda:citas_asignadas')

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
                    messages.info(request, "El pago de esta cita ya se encontraba registrado como realizado.")
                    return redirect('agenda:citas_asignadas')
                
                pago.estado = 'Realizado'
                pago.save()
                
            messages.success(request, "Pago registrado correctamente.")
            
    except Exception as e:
        # Control de excepciones ante fallos de base de datos
        messages.error(request, "Ocurrió un error inesperado al procesar el registro del pago.")

    return redirect('agenda:citas_asignadas')




@login_required(login_url="agenda:login")
@requiere_rol("ADMINISTRADOR")
@require_POST  
@transaction.atomic
def cambiar_estado_cita_admin(request, cita_id, nuevo_estado):
    if not cita_id:
        messages.error(request, "Identificador de cita no válido.")
        return redirect('agenda:ver_todas_citas')

    cita = get_object_or_404(Citas, id=cita_id)
    
    # Normalizamos el estado recibido (minúsculas y sin espacios) para evitar fallos de coincidencia
    nuevo_estado_normalizado = nuevo_estado.strip().lower()
    
    estados_validos = dict(Citas.ESTADOS_CITA)
    
    if nuevo_estado_normalizado not in estados_validos:
        messages.error(request, f"El estado seleccionado '{nuevo_estado}' no es válido.")
        return redirect('agenda:ver_todas_citas')

    if cita.estado == nuevo_estado_normalizado:
        messages.warning(request, f"La cita ya se encuentra en estado '{estados_validos[nuevo_estado_normalizado]}'.")
        return redirect('agenda:ver_todas_citas')

    try:
        with transaction.atomic():
            cita.estado = nuevo_estado_normalizado
            cita.save()
            messages.success(request, f"Estado actualizado a '{estados_validos[nuevo_estado_normalizado]}'.")
            
    except Exception as e:
        messages.error(request, "Ocurrió un error interno al intentar actualizar el estado de la cita.")

    return redirect('agenda:ver_todas_citas')




@require_POST  # Seguridad nativa: Rechaza cualquier acceso por GET directamente a nivel de decorador
@requiere_rol("ADMINISTRADOR")
def registrar_pago_admin(request, cita_id):
    # Control de seguridad: Validar que el ID exista
    if not cita_id:
        messages.error(request, "Identificador de cita no válido.")
        return redirect('agenda:ver_todas_citas')

    # Obtener la cita globalmente para el rol de administrador
    cita = get_object_or_404(Citas, id=cita_id)
    
    # Capturar y limpiar el método de pago elegido en el <select> del HTML
    metodo_seleccionado = request.POST.get('metodo_pago', 'Efectivo').strip()
    
    # Validar que el método de pago no esté vacío por seguridad o manipulación del DOM
    if not metodo_seleccionado:
        metodo_seleccionado = 'Efectivo'

    try:
        # Robustez: Transacción atómica para blindar la operación en base de datos
        with transaction.atomic():
            pago, creado = Pagos.objects.get_or_create(
                citas=cita,
                defaults={
                    'valor': cita.total,
                    'estado': 'Realizado',
                    'metodo_pago': metodo_seleccionado
                }
            )
            
            # Si ya existía, actualizamos estado y método seleccionado
            if not creado:
                if pago.estado == 'Realizado' and pago.metodo_pago == metodo_seleccionado:
                    messages.info(request, "El pago de esta cita ya se encontraba registrado con los mismos datos.")
                    return redirect('agenda:ver_todas_citas')
                
                pago.estado = 'Realizado'
                pago.metodo_pago = metodo_seleccionado
                pago.save()
                
            messages.success(request, f"Pago registrado correctamente por {metodo_seleccionado}.")
            
    except Exception as e:
        # Control de excepciones ante fallos imprevistos de base de datos
        messages.error(request, "Ocurrió un error interno al intentar registrar el pago de la cita.")

    return redirect('agenda:ver_todas_citas')


#CRUD SERVICIOS

from django.db import DatabaseError
@requiere_rol("ADMINISTRADOR", "CLIENTE", "MANICURISTA")
def ver_servicio(request):
    try:
        # Robustez: Consulta segura de los servicios registrados
        s = Servicios.objects.all()
        
        contexto = {
            "datos": s
        }
    except DatabaseError as e:
        # Control de excepciones: Si la base de datos falla, evitamos que la página rompa en crudo
        s = []
        contexto = {
            "datos": s
        }
        messages.error(request, "Ocurrió un error al intentar cargar el catálogo de servicios.")

    return render(request, "servicio/servicios.html", contexto)

@require_http_methods(["GET", "POST"])  # Seguridad: Permite únicamente métodos GET y POST estándar
@requiere_rol("ADMINISTRADOR")
def crear_servicio(request):
    if request.method == "POST":
        # Capturar y limpiar los campos del formulario
        nombre = request.POST.get('nombre', '').strip()
        precio = request.POST.get('precio', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        duracion = request.POST.get('duracion', '').strip()

        # Control de validación: Asegurar que los campos obligatorios no vengan vacíos
        if not nombre or not precio or not duracion:
            messages.error(request, "Por favor completa todos los campos obligatorios del servicio.")
            return redirect("agenda:servicios") # O renderizar de nuevo el formulario con los datos

        try:
            # Robustez: Usar transacción atómica para garantizar la integridad al guardar
            with transaction.atomic():
                s = Servicios(
                    nombre=nombre,
                    precio=precio,
                    descripcion=descripcion,
                    duracion=duracion,
                )
                s.save()
                messages.success(request, f"Servicio '{nombre}' creado con éxito!")
                
        except DatabaseError as e:
            # Control ante fallos específicos de base de datos
            messages.error(request, "Ocurrió un error en la base de datos al intentar guardar el servicio.")
        except Exception as e:
            # Control ante cualquier eventualidad imprevista
            messages.error(request, "Ocurrió un error inesperado al procesar la solicitud.")
            
        return redirect("agenda:servicios")
    
    # Si la petición es GET, renderizamos el formulario con normalidad
    return render(request, "servicio/formulario_servicio.html")
   


@require_POST  # Seguridad crítica: Impide que se eliminen servicios mediante una petición GET o enlaces directos
@requiere_rol("ADMINISTRADOR")
def eliminar_servicio(request, id):
    # Control de seguridad: Validar existencia del ID antes de procesar
    if not id:
        messages.error(request, "Identificador de servicio no válido.")
        return redirect("agenda:servicios")

    try:
        # Robustez: Usar transacción atómica junto con get_object_or_404 para mayor limpieza
        with transaction.atomic():
            s = get_object_or_404(Servicios, pk=id)
            nombre_servicio = s.nombre  # Guardamos el nombre antes de borrarlo para el mensaje
            s.delete()
            messages.success(request, f"Servicio '{nombre_servicio}' eliminado correctamente.")
            
    except IntegrityError:
        # Control de integridad: Salta si el servicio está asociado a citas u otras tablas foráneas
        messages.info(request, "No es posible eliminar el servicio porque se encuentra asociado a registros existentes.")
    except Exception as e:
        # Control genérico ante cualquier eventualidad imprevista
        messages.error(request, "Ocurrió un error inesperado al intentar eliminar el servicio.")

    return redirect("agenda:servicios")


@require_http_methods(["GET", "POST"])  # Seguridad: Restringe a métodos HTTP estándar permitidos
@requiere_rol("ADMINISTRADOR")
def actualizar_servicio(request, id):
    # Control de seguridad: Validar existencia del ID antes de continuar
    if not id:
        messages.error(request, "Identificador de servicio no válido.")
        return redirect("agenda:servicios")

    # Obtener el servicio de forma segura (lanza 404 si no existe)
    s = get_object_or_404(Servicios, pk=id)

    if request.method == "POST":
        # Capturar y limpiar los campos enviados en el formulario
        nombre = request.POST.get('nombre', '').strip()
        precio = request.POST.get('precio', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        duracion = request.POST.get('duracion', '').strip()

        # Validación de campos obligatorios
        if not nombre or not precio or not duracion:
            messages.error(request, "Por favor completa todos los campos obligatorios del servicio.")
            return redirect("agenda:servicios")

        try:
            # Robustez: Transacción atómica para asegurar la actualización en base de datos
            with transaction.atomic():
                s.nombre = nombre
                s.precio = precio
                s.descripcion = descripcion
                s.duracion = duracion
                s.save()
                
                messages.success(request, f"Servicio '{s.nombre}' actualizado correctamente.")
                
        except DatabaseError:
            # Control específico ante fallos de base de datos
            messages.error(request, "Ocurrió un error en la base de datos al intentar actualizar el servicio.")
        except Exception as e:
            # Control genérico ante eventualidades imprevistas
            messages.error(request, "Ocurrió un error inesperado al procesar la actualización.")
           
        return redirect("agenda:servicios")
    
    # Si la petición es GET, enviamos el objeto actual al formulario para prellenarlo
    contexto = {
        "datos": s
    }
    return render(request, "servicio/formulario_servicio.html", contexto)



#CRUD INVENTARIO
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

def lista_movimientos(request):
    movimientos = MovimientoInventario.objects.select_related('producto').all().order_by('-fecha')
    return render(request, 'inventario/movimientos.html', {'movimientos': movimientos})

@require_POST
@transaction.atomic
def registrar_movimiento(request):
    producto_id = request.POST.get('producto')
    tipo = request.POST.get('tipo')
    cantidad_str = request.POST.get('cantidad')
    motivo = request.POST.get('motivo', '').strip()
    
    # 1. Validar que el tipo de movimiento sea estrictamente los permitidos
    if tipo not in ['Entrada', 'Salida']:
        messages.error(request, "Tipo de movimiento no válido.")
        return redirect('agenda:ver_inventario')
    
    # 2. Validar que el producto exista (evita manipulación de IDs ajenos o inexistentes)
    producto = get_object_or_404(Inventario, id=producto_id)
    
    # 3. Validar cantidad numérica y positiva (Blindaje contra inyección de negativos desde el cliente)
    try:
        cantidad = int(cantidad_str)
        if cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor a cero.")
    except (TypeError, ValueError):
        messages.error(request, "La cantidad ingresada no es válida.")
        return redirect('agenda:registrar_movimiento')
    
    # 4. Validar motivo obligatorio y longitud mínima/máxima para seguridad
    if not motivo or len(motivo) < 3:
        messages.error(request, "Debes proporcionar un motivo válido (mínimo 3 caracteres).")
        return redirect('agenda:registrar_movimiento')
    
    # 5. Validación estricta de stock en salidas (Evita stock negativo en backend)
    if tipo == 'Salida' and producto.cantidad < cantidad:
        messages.error(request, f"Acción denegada: Stock insuficiente. Stock actual de '{producto.nombre}': {producto.cantidad}.")
        return redirect('agenda:registrar_movimiento')
    
    # 6. Actualización segura de inventario
    if tipo == 'Entrada':
        producto.cantidad += cantidad
    elif tipo == 'Salida':
        producto.cantidad -= cantidad
    
    producto.save()
    
    # 7. Registrar el movimiento oficial
    MovimientoInventario.objects.create(
        producto=producto,
        tipo=tipo,
        cantidad=cantidad,
        motivo=motivo
    )
    
    messages.success(request, f"Movimiento de {tipo.lower()} registrado con éxito para '{producto.nombre}'.")
    return redirect('agenda:ver_inventario')


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





# ----VISTA RECIBO----
@login_required(login_url="agenda:login")
@requiere_rol("CLIENTE")
def recibo(request, id):
    if not id:
        messages.error(request, "Identificador de cita no válido.")
        return redirect('agenda:mis_citas')

    try:
        # 1. Obtener el cliente actual para asegurar que la cita le pertenezca
        cliente = Clientes.objects.filter(user=request.user).first()
        cita = get_object_or_404(Citas, pk=id, cliente=cliente)

        # 2. Obtener el pago relacionado usando la relación inversa
        pago = cita.pagos.first()

        # 3. Validaciones corregidas (minúscula en estado y existencia de pago)
        if cita.estado != "completada" or not pago:
            messages.warning(request, "El recibo solo está disponible para citas completadas y pagadas.")
            return redirect('agenda:mis_citas')

        # 4. Obtener o crear el recibo
        recibo_obj, created = Recibo.objects.get_or_create(
            pago=pago,
            defaults={
                'detalle': f"Servicio realizado: {cita.servicios.nombre}"
            }
        )

        contexto = {
            "recibo": recibo_obj,
            "cita": cita,
            "pago": pago,
        }

    except DatabaseError:
        messages.error(request, "Ocurrió un error al intentar generar el recibo de la cita.")
        return redirect('agenda:mis_citas')

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

    # Filtrado estricto según ID y Rol del usuario en sesión
    if rol_nombre == "CLIENTE":
        try:
            cliente = Clientes.objects.get(user=request.user)
            citas = Citas.objects.filter(cliente=cliente).select_related('servicios', 'manicurista')
        except Clientes.DoesNotExist:
            return JsonResponse([], safe=False)

    elif rol_nombre == "MANICURISTA":
        try:
            manicurista = Manicurista.objects.get(user=request.user)
            citas = Citas.objects.filter(manicurista=manicurista).select_related('servicios', 'cliente')
        except Manicurista.DoesNotExist:
            return JsonResponse([], safe=False)

    else:
        # ADMINISTRADOR o superusuario ve todas las citas del sistema
        citas = Citas.objects.all().select_related('servicios', 'cliente', 'manicurista')

    for cita in citas:
        # Crear timestamp de inicio
        start_dt = datetime.combine(cita.fecha, cita.hora)
        
        # Duración segura (manejando tanto si usa duracion_horas o duracion en minutos)
        if cita.servicios and hasattr(cita.servicios, 'duracion_horas'):
            duracion_min = int(cita.servicios.duracion_horas * 60)
        elif cita.servicios and hasattr(cita.servicios, 'duracion') and cita.servicios.duracion:
            duracion_min = cita.servicios.duracion
        else:
            duracion_min = 60 # Valor por defecto de 1 hora si no está definido

        end_dt = start_dt + timedelta(minutes=duracion_min)

        # Configurar título dinámico según la perspectiva del usuario
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