
from django.urls import reverse

from .models import (
    Notificacion,
    Pagos,
    Recibo,
    Resena,
    PerfilUsuario,
)


# ============================================================
# 1. OBTENER LA VISTA SEGÚN EL ROL DEL USUARIO
# ============================================================

def obtener_url_citas(usuario):
    """
    Devuelve la ruta de citas correspondiente al rol.
    """

    perfil = (
        PerfilUsuario.objects
        .filter(user=usuario)
        .select_related("rol")
        .first()
    )

    if not perfil or not perfil.rol:
        return reverse("agenda:dashboard")

    rol = perfil.rol.nombre.strip().upper()

    if rol == "CLIENTE":
        return reverse("agenda:mis_citas")

    if rol == "MANICURISTA":
        return reverse("agenda:citas_asignadas")

    if rol == "ADMINISTRADOR":
        return reverse("agenda:ver_todas_citas")

    return reverse("agenda:dashboard")


# ============================================================
# 2. CREAR NOTIFICACIÓN PARA EL CLIENTE
# ============================================================

def crear_notificacion_cita(
    cita,
    tipo,
    titulo,
    mensaje,
    url="",
):
    """
    Crea una notificación para el cliente.
    Evita duplicados con el mismo tipo y título para una cita.
    """

    usuario = getattr(cita.cliente, "user", None)

    if usuario is None:
        return None

    if not url:
        url = reverse("agenda:mis_citas")

    notificacion, creada = Notificacion.objects.get_or_create(
        destinatario=usuario,
        cita=cita,
        tipo=tipo,
        titulo=titulo,
        defaults={
            "mensaje": mensaje,
            "url": url,
        },
    )

    return notificacion


# ============================================================
# 3. NOTIFICAR A LA MANICURISTA Y A LOS ADMINISTRADORES
# ============================================================

def notificar_equipo_cita(
    cita,
    tipo,
    titulo,
    mensaje,
):
    """
    Notifica a la manicurista asignada y a los administradores.
    Cada destinatario recibe su URL según el rol.
    """

    destinatarios = {}

    # Manicurista asignada a la cita
    usuario_manicurista = getattr(
        cita.manicurista,
        "user",
        None,
    )

    if usuario_manicurista:
        destinatarios[usuario_manicurista.pk] = (
            usuario_manicurista
        )

    # Administradores con el rol correspondiente
    perfiles_admin = (
        PerfilUsuario.objects
        .filter(rol__nombre__iexact="ADMINISTRADOR")
        .select_related("user")
    )

    for perfil in perfiles_admin:
        destinatarios[perfil.user_id] = perfil.user

    # Crear una notificación por destinatario y evento
    for usuario in destinatarios.values():
        Notificacion.objects.create(
            destinatario=usuario,
            cita=cita,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            url=obtener_url_citas(usuario),
        )


# ============================================================
# 4. CITA AGENDADA
# ============================================================

def notificar_cita_agendada(cita):
    """
    Notifica al cliente, a la manicurista y a los administradores.
    """

    fecha = cita.fecha.strftime("%d/%m/%Y")
    hora = cita.hora.strftime("%I:%M %p")

    servicio = cita.servicios.nombre
    manicurista = str(cita.manicurista)
    total = f"${cita.total:,.0f}".replace(",", ".")

    mensaje_cliente = (
        f"Tu cita para {servicio} quedó agendada para el "
        f"{fecha} a las {hora}, con {manicurista}. "
        f"Total a pagar: {total} COP."
    )

    if cita.descuento_aplicado:
        precio_original = (
            cita.precio_original or cita.servicios.precio
        )

        precio_original = (
            f"${precio_original:,.0f}".replace(",", ".")
        )

        descuento = (
            f"${cita.descuento_aplicado:,.0f}".replace(",", ".")
        )

        mensaje_cliente += (
            f" Precio original: {precio_original} COP."
            f" Descuento aplicado: {descuento} COP."
        )

    # Notificación al cliente
    crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.CITA_AGENDADA,
        titulo="¡Tu cita ha sido agendada!",
        mensaje=mensaje_cliente,
        url=reverse("agenda:mis_citas"),
    )

    # Notificación a la manicurista y administradores
    mensaje_equipo = (
        f"Nueva cita para el {fecha} a las {hora}. "
        f"Cliente: {cita.cliente}. "
        f"Servicio: {servicio}. "
        f"Manicurista: {manicurista}."
    )

    notificar_equipo_cita(
        cita=cita,
        tipo=Notificacion.Tipo.CITA_AGENDADA,
        titulo="Nueva cita agendada",
        mensaje=mensaje_equipo,
    )


# ============================================================
# 5. CITA MODIFICADA
# ============================================================

def notificar_cita_modificada(cita):
    """
    Notifica cuando se modifica la fecha, hora u otro dato de la cita.
    """

    fecha = cita.fecha.strftime("%d/%m/%Y")
    hora = cita.hora.strftime("%I:%M %p")

    servicio = cita.servicios.nombre

    # Notificación al cliente
    crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.CITA_MODIFICADA,
        titulo="Tu cita ha sido modificada",
        mensaje=(
            f"Tu cita para {servicio} fue actualizada. "
            f"Nueva fecha: {fecha}, hora: {hora}. "
            "Consulta tus citas para ver los detalles."
        ),
        url=reverse("agenda:mis_citas"),
    )

    # Notificación al equipo
    notificar_equipo_cita(
        cita=cita,
        tipo=Notificacion.Tipo.CITA_MODIFICADA,
        titulo="Cita modificada",
        mensaje=(
            f"La cita del cliente {cita.cliente} fue modificada. "
            f"Nueva fecha: {fecha}, hora: {hora}. "
            f"Servicio: {servicio}."
        ),
    )


# ============================================================
# 6. CITA CANCELADA
# ============================================================

def notificar_cita_cancelada(cita):
    """
    Notifica la cancelación al cliente, a la manicurista
    y a los administradores.
    """

    fecha = cita.fecha.strftime("%d/%m/%Y")
    hora = cita.hora.strftime("%I:%M %p")

    servicio = cita.servicios.nombre

    # Notificación al cliente
    crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.CITA_CANCELADA,
        titulo="Tu cita ha sido cancelada",
        mensaje=(
            f"La cita de {servicio}, programada para el "
            f"{fecha} a las {hora}, ha sido cancelada."
        ),
        url=reverse("agenda:mis_citas"),
    )

    # Notificación al equipo
    notificar_equipo_cita(
        cita=cita,
        tipo=Notificacion.Tipo.CITA_CANCELADA,
        titulo="Cita cancelada",
        mensaje=(
            f"La cita del cliente {cita.cliente}, programada "
            f"para el {fecha} a las {hora}, ha sido cancelada. "
            f"Servicio: {servicio}."
        ),
    )


# ============================================================
# 7. RESEÑA PENDIENTE
# ============================================================

def notificar_resena_pendiente(cita):
    """
    Invita al cliente a dejar una reseña si aún no existe.
    """

    if Resena.objects.filter(cita=cita).exists():
        return None

    return crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.RESENA_PENDIENTE,
        titulo="¡Cuéntanos cómo fue tu experiencia!",
        mensaje=(
            f"Tu cita de {cita.servicios.nombre} ya fue "
            "completada. Si lo deseas, puedes dejar una reseña."
        ),
        url=reverse(
            "agenda:crear_resena",
            args=[cita.pk],
        ),
    )


# ============================================================
# 8. CREAR RECIBO Y NOTIFICAR AL CLIENTE
# ============================================================

def crear_recibo_y_notificar(cita):
    """
    Crea el recibo si hay un pago realizado y notifica al cliente.
    """

    if cita.estado != "completada":
        return None

    pago = (
        Pagos.objects
        .filter(citas=cita, estado="Realizado")
        .order_by("-fecha_pago", "-id")
        .first()
    )

    if pago is None:
        return None

    recibo, _ = Recibo.objects.get_or_create(
        pago=pago,
        defaults={
            "detalle": (
                f"Servicio realizado: {cita.servicios.nombre}"
            ),
        },
    )

    crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.RECIBO_DISPONIBLE,
        titulo="Tu recibo está disponible",
        mensaje=(
            f"Ya puedes consultar el recibo de tu cita de "
            f"{cita.servicios.nombre} del "
            f"{cita.fecha:%d/%m/%Y}."
        ),
        url=reverse(
            "agenda:recibo",
            args=[cita.pk],
        ),
    )

    return recibo


def notificar_inventario_bajo(producto):
    """
    Notifica a los administradores cuando un producto
    tiene stock bajo o está agotado.
    """

    estado = str(producto.estado_stock).strip().lower()

    if estado == "agotado":
        titulo = "¡Insumo agotado!"
        mensaje = (
            f"El insumo '{producto.nombre}' está agotado. "
            "Es necesario revisar y reponer las existencias."
        )
    elif estado == "stock bajo":
        titulo = "Stock bajo de inventario"
        mensaje = (
            f"El insumo '{producto.nombre}' tiene "
            f"{producto.cantidad} unidades disponibles. "
            "Revisa si es necesario reponerlo."
        )
    else:
        # No notificar si el stock es suficiente
        return

    url_inventario = reverse("agenda:ver_inventario")

    administradores = (
        PerfilUsuario.objects
        .filter(rol__nombre__iexact="ADMINISTRADOR")
        .select_related("user")
    )

    for perfil in administradores:
        if not perfil.user_id:
            continue

        # Evitar duplicar alertas pendientes del mismo producto
        existe = Notificacion.objects.filter(
            destinatario=perfil.user,
            tipo=Notificacion.Tipo.INVENTARIO_BAJO,
            titulo=titulo,
            mensaje=mensaje,
            url=url_inventario,
            leida=False,
        ).exists()

        if not existe:
            Notificacion.objects.create(
                destinatario=perfil.user,
                tipo=Notificacion.Tipo.INVENTARIO_BAJO,
                titulo=titulo,
                mensaje=mensaje,
                url=url_inventario,
            )
