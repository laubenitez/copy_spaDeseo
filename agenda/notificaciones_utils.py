from django.urls import reverse

from .models import Notificacion, Pagos, Recibo, Resena


def crear_notificacion_cita(cita, tipo, titulo, mensaje, url=""):
    """
    Crea una notificación para el cliente de la cita.
    Evita duplicados del mismo tipo y título para una misma cita.
    """
    cliente = cita.cliente
    usuario = getattr(cliente, "user", None)

    if usuario is None:
        return None

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

    # Si ya existía, no se duplica ni se sobrescribe su estado de lectura.
    return notificacion


def notificar_cita_agendada(cita):
    servicio = cita.servicios.nombre
    manicurista = str(cita.manicurista)
    fecha = cita.fecha.strftime("%d/%m/%Y")
    hora = cita.hora.strftime("%I:%M %p")

    total = f"${cita.total:,.0f}".replace(",", ".")

    mensaje = (
        f"Tu cita para {servicio} quedó agendada para el "
        f"{fecha} a las {hora}, con {manicurista}. "
        f"Total a pagar: {total} COP."
    )

    if cita.descuento_aplicado:
        precio_original = cita.precio_original or cita.servicios.precio
        precio_original = f"${precio_original:,.0f}".replace(",", ".")
        descuento = f"${cita.descuento_aplicado:,.0f}".replace(",", ".")

        mensaje += (
            f" Precio original: {precio_original} COP."
            f" Descuento aplicado: {descuento} COP."
        )

    return crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.CITA_AGENDADA,
        titulo="¡Tu cita ha sido agendada!",
        mensaje=mensaje,
        url=reverse("agenda:mis_citas"),
    )



def notificar_cita_modificada(cita):
    from django.urls import reverse
    from .models import Notificacion

    usuario = getattr(cita.cliente, "user", None)

    if usuario is None:
        return None

    fecha = cita.fecha.strftime("%d/%m/%Y")
    hora = cita.hora.strftime("%I:%M %p")

    return Notificacion.objects.create(
        destinatario=usuario,
        cita=cita,
        tipo=Notificacion.Tipo.CITA_MODIFICADA,
        titulo="Tu cita ha sido modificada",
        mensaje=(
            f"Tu cita para {cita.servicios.nombre} fue actualizada. "
            f"Nueva fecha: {fecha}, hora: {hora}. "
            "Consulta tus citas para ver los detalles."
        ),
        url=reverse("agenda:mis_citas"),
    )



def notificar_cita_cancelada(cita):
    return crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.CITA_CANCELADA,
        titulo="Tu cita ha sido cancelada",
        mensaje=(
            f"La cita de {cita.servicios.nombre}, programada para "
            f"el {cita.fecha:%d/%m/%Y} a las {cita.hora:%I:%M %p}, "
            "ha sido cancelada."
        ),
        url=reverse("agenda:mis_citas"),
    )


def notificar_resena_pendiente(cita):
    # No invitar a dejar una reseña si ya existe una.
    if Resena.objects.filter(cita=cita).exists():
        return None

    return crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.RESENA_PENDIENTE,
        titulo="¡Cuéntanos cómo fue tu experiencia!",
        mensaje=(
            f"Tu cita de {cita.servicios.nombre} ya fue completada. "
            "Si lo deseas, puedes dejar una reseña sobre tu experiencia."
        ),
        url=reverse("agenda:crear_resena", args=[cita.pk]),
    )


def crear_recibo_y_notificar(cita):
    """
    Crea el recibo si existe un pago realizado y avisa al cliente.
    Se puede llamar varias veces sin duplicar el recibo ni la notificación.
    """
    if cita.estado != "completada":
        return None


    pago = (
        Pagos.objects.filter(citas=cita, estado="Realizado")
        .order_by("-fecha_pago", "-id")
        .first()
    )

    if pago is None:
        return None

    recibo, _ = Recibo.objects.get_or_create(
        pago=pago,
        defaults={
            "detalle": f"Servicio realizado: {cita.servicios.nombre}"
        },
    )

    crear_notificacion_cita(
        cita=cita,
        tipo=Notificacion.Tipo.RECIBO_DISPONIBLE,
        titulo="Tu recibo está disponible",
        mensaje=(
            f"Ya puedes consultar el recibo de tu cita de "
            f"{cita.servicios.nombre} del {cita.fecha:%d/%m/%Y}."
        ),
        url=reverse("agenda:recibo", args=[cita.pk]),
    )

    return recibo
