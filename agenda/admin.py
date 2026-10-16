
from django.contrib import admin
from .models import *


@admin.register(Rol)


class Rol(admin.ModelAdmin):
    list_display = [
        "nombre",
        "descripcion",
        
    ]


@admin.register(PerfilUsuario)


class PerfilUsuario(admin.ModelAdmin):
    list_display = [
        "user",
        "rol",
        
    ]


@admin.register(Clientes)


class ClientesAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "nombre",
        "apellido",
        "telefono",
        "email",
    ]


@admin.register(Manicurista)



class ManicuristaAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "nombre",
        "apellido",
        "telefono",
        "email",
        "especialidad",
        "fecha_ingreso",
        "estado"
    ]


@admin.register(Servicios)


class ServiciosAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "nombre",
        "precio",
        "duracion"
    ]
    search_fields = [
        "nombre"
    ]


@admin.register(Citas)


class CitasAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "cliente",
        "manicurista",
        "servicios",
        "fecha",
        "hora",
        "total",
    ]

@admin.register(Inventario)


class InventarioAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "nombre",
        "categoria",
        "cantidad",
        "stock_minimo",
        "estado_stock"
    ]
    search_fields = [
        "nombre",
        "categoria"
    ]


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "producto",
        "tipo",
        "cantidad",
        "fecha",
    ]
    search_fields = [
        "tipo",
        "fecha"
    ] 


@admin.register(Pagos)

class PagosAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "citas",
        "fecha_pago",
        "metodo_pago",
        "estado",
        "valor"
    ]
    search_fields = [
        "fecha_pago",
        "valor"

    ]

    @admin.register(Administrador)


    class AdministradorAdmin(admin.ModelAdmin):
        list_display = [
            "id",
            "nombre",
            "apellido",
            "telefono",
            "email",
        ]

@admin.register(SolicitudSoporte)
class SolicitudSoporteAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "nombre_solicitante",
        "rol_solicitante",
        "asunto",
        "estado",
        "fecha_creacion",
        "fecha_resolucion",
    )

    list_filter = (
        "estado",
        "rol_solicitante",
        "fecha_creacion",
    )

    search_fields = (
        "nombre_solicitante",
        "asunto",
        "descripcion",
        "respuesta",
    )

    readonly_fields = (
        "fecha_creacion",
        "fecha_resolucion",
    )

    ordering = (
        "-fecha_creacion",
    )

@admin.register(Descuentos)
class DescuentosAdmin(admin.ModelAdmin):
    list_display = (
    "id",
    "nombre",
    "tipo",
    "tipo_beneficio",
    "valor",
    "fecha_inicio",
    "fecha_fin",
    "activo",
    "vigente",
    )

    list_filter = (
        "tipo",
        "tipo_beneficio",
        "activo",
        "fecha_inicio",
        "fecha_fin",
    )

    search_fields = (
        "nombre",
        "descripcion",
    )

    ordering = (
        "-fecha_inicio",
    )

    readonly_fields = (
        "fecha_creacion",
        "fecha_actualizacion",
    )

    fieldsets = (
        ("Información de la promoción", {
            "fields": (
                "nombre",
                "descripcion",
                "tipo",
                "activo",
            )
        }),
        ("Beneficio", {
            "fields": (
                "tipo_beneficio",
                "valor",
            )
        }),
        ("Vigencia", {
            "fields": (
                "fecha_inicio",
                "fecha_fin",
            )
        }),
        ("Auditoría", {
            "fields": (
                "fecha_creacion",
                "fecha_actualizacion",
            )
        }),
    )

@admin.register(PreferenciasUsuario)
class PreferenciasUsuarioAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "verificacion_adicional",
        "recordatorios_whatsapp",
        "permitir_comunicaciones",
    )

    list_filter = (
        "verificacion_adicional",
        "recordatorios_whatsapp",
        "permitir_comunicaciones",
    )

    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )

    list_editable = (
        "verificacion_adicional",
        "recordatorios_whatsapp",
        "permitir_comunicaciones",
    )

    ordering = ("user__username",)