
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