from django.urls import path, include
from . import views
from rest_framework import routers
from django.contrib.auth.views import LogoutView

router = routers.DefaultRouter()

router.register("clientes", views.ClientesViewSet)
router.register("manicuristas", views.ManicuristaViewSet)
router.register("servicios", views.ServiciosViewSet)
router.register("citas", views.CitasViewSet)
router.register("inventario", views.InventarioViewSet)
router.register("pagos", views.PagosViewSet)
router.register("recibos", views.ReciboViewSet)
router.register("gastos", views.GastosViewSet)


app_name = "agenda"

urlpatterns = [
     path('api/auth/logout/', LogoutView.as_view(), name='api_logout'),


    path('v1/', include(router.urls)),

    path('', views.index, name="index"),
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("register/", views.register, name="register"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path('ajustes/', views.ajustes, name='ajustes'),
    path('soporte/', views.soporte, name='soporte'),
    path('calendario/', views.ver_calendario, name='ver_calendario'),
    path('api/citas/', views.obtener_citas_json, name='obtener_citas_json'),


    #Clientes
    path('ver_cliente/', views.ver_cliente, name="ver_cliente"),
    path('crear_cliente/', views.crear_cliente, name="crear_cliente"),
    path('eliminar_cliente/<int:id>/', views.eliminar_cliente, name="eliminar_cliente"),
    path('actualizar_cliente/<int:id>/', views.actualizar_cliente, name="actualizar_cliente"),
    path('editar_perfil/', views.editar_perfil, name="editar_perfil"),
    path('crear_resena/<int:cita_id>/', views.crear_resena, name='crear_resena'),
    path('mis_resenas/', views.mis_resenas, name='mis_resenas'),
    path("mis_citas/", views.mis_citas, name="mis_citas"),

    #Citas
    path('ver_citas/', views.ver_citas, name="ver_citas"),
    path('crear_citas/', views.crear_citas, name="crear_citas"),
    path('eliminar_citas/<int:id>/', views.eliminar_citas, name="eliminar_citas"),
    path('actualizar_citas/<int:id>/', views.actualizar_citas, name="actualizar_citas"),

    #Manicurista
    path('citas_asignadas', views.citas_asignadas, name="citas_asignadas"),
    path('cita/<int:cita_id>/estado/<str:nuevo_estado>/', views.cambiar_estado_cita, name='cambiar_estado_cita'),
    path('cita/pago/<int:cita_id>/', views.registrar_pago_cita, name='registrar_pago_cita'),


    # Admin
    path('ver_todas_citas/', views.ver_todas_citas, name='ver_todas_citas'),
    path('resenas/', views.ver_todas_resenas, name='ver_resenas'),
    path('ver_manicuristas/', views.ver_manicuristas, name='ver_manicuristas'),
    path("manicuristas/crear/", views.crear_manicurista, name="crear_manicurista"),
    path("manicuristas/editar/<int:id>/", views.actualizar_manicurista, name="actualizar_manicurista"),
    path("manicuristas/eliminar/<int:id>/", views.eliminar_manicurista, name="eliminar_manicurista"),
    path('admin/cita/estado/<int:cita_id>/<str:nuevo_estado>/', views.cambiar_estado_cita_admin, name='cambiar_estado_admin'),
    path('admin/cita/pago/<int:cita_id>/', views.registrar_pago_admin, name='registrar_pago_admin'),
    path('ver_inventario/', views.ver_inventario, name="ver_inventario"),
    path('crear_inventario/', views.crear_inventario, name="crear_inventario"),
    path('actualizar_inventario/<int:id>/', views.actualizar_inventario, name="actualizar_inventario"),
    path('eliminar_inventario/<int:id>/', views.eliminar_inventario, name="eliminar_inventario"),
    path('inventario/movimientos/', views.lista_movimientos, name='lista_movimientos'),
    path('inventario/movimientos/registrar/', views.registrar_movimiento, name='registrar_movimiento'),



    #Servicio
    path('servicios/', views.ver_servicio, name="ver_servicio"),
    path('crear_servicio/', views.crear_servicio, name="crear_servicio"),
    path('eliminar_servicio/<int:id>/', views.eliminar_servicio, name="eliminar_servicio"),
    path('actualizar_servicio/<int:id>/', views.actualizar_servicio, name="actualizar_servicio"),

    
    #Inventario
    path('ver_inventario/', views.ver_inventario, name="ver_inventario"),
    path('crear_inventario/', views.crear_inventario, name="crear_inventario"),
    path('eliminar_inventario/<int:id>/', views.eliminar_inventario, name="eliminar_inventario"),
    path('actualizar_inventario/<int:id>/', views.actualizar_inventario, name="actualizar_inventario"),

    #Pagos
    path('pagos/', views.ver_pagos, name="ver_pagos"),
    path('crear_pago/', views.crear_pago, name="crear_pago"),
    path('eliminar_pago/<int:id>/', views.eliminar_pago, name="eliminar_pago"),
    path('actualizar_pago/<int:id>/', views.actualizar_pago, name="actualizar_pago"),

    #recibo
    path('recibo/<int:id>/', views.recibo, name="recibo"),

    #Gastos
    path('gastos/', views.ver_gasto, name="ver_gasto"),
    path('crear_gastos/', views.crear_gastos, name="crear_gastos"),
    path('eliminar_gastos/<int:id>/', views.eliminar_gastos, name="eliminar_gastos"),
    path('actualizar_gastos/<int:id>/', views.actualizar_gastos, name="actualizar_gastos"),



]
