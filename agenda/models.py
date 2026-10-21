from django.db import models
from django.contrib.auth.models import User
from .validators import validar_imagen_portafolio
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

class Rol(models.Model):
    # Ejemplo de registros: 'ADMINISTRADOR', 'VENDEDOR', 'CLIENTE'
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre

class PerfilUsuario(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - Rol: {self.rol.nombre if self.rol else 'Sin Rol'}"


class Clientes(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cliente"
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(max_length=100)
    password = models.CharField(max_length=100, blank=True, null=True)
    fecha_nacimiento = models.DateField(null=True, blank=True, verbose_name="Fecha de nacimiento")
    foto_perfil = models.ImageField(upload_to='perfiles/',null=True, blank=True)



    def __str__(self):
        return f"{self.id} - {self.nombre} {self.apellido}"


class Manicurista(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manicurista"
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(max_length=100)
    password = models.CharField(max_length=100)
    especialidad = models.CharField(max_length=100)
    fecha_ingreso = models.DateField()
    ESTADO = (
        ("Activa", "ACTIVA"),
        ("Inactiva", "INACTIVA"),
    )
    estado = models.CharField(
        max_length= 20,
        choices=ESTADO,
        default="Activa"
    )
    foto_perfil = models.ImageField(upload_to='perfiles/',null=True, blank=True)


    def __str__(self):
        return f"{self.id} - {self.nombre} {self.apellido}"

class PortafolioManicurista(models.Model):
    manicurista = models.ForeignKey(
        Manicurista,
        on_delete=models.CASCADE,
        related_name="portafolio"
    )

    titulo = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    imagen = models.ImageField(
        upload_to="portafolio/",
        validators=[validar_imagen_portafolio]
    )
    categoria = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    visible = models.BooleanField(default=True)
    fecha_publicacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.titulo} - {self.manicurista.nombre} {self.manicurista.apellido}"


class Servicios(models.Model):
    nombre = models.CharField(max_length=100)
    precio = models.IntegerField()
    porcentaje_comision = models.IntegerField(default=50, help_text="Porcentaje de comisión para la manicurista")
    descripcion = models.TextField(null=True, blank=True)
    imagen = models.ImageField(
        upload_to="servicios/",
        blank=True,
        null=True,
        verbose_name="Fotografía del servicio"
    )

    ESTADOS = (
        ("Activo", "ACTIVO"),
        ("Inactivo", "INACTIVO"),
    )
    estado = models.CharField(choices=ESTADOS, default="Activo", max_length=8)
    duracion = models.IntegerField(
        help_text="Duracion en minutos"
    )


    def __str__(self):
        return f"{self.id} - {self.nombre}"



class Citas(models.Model):
    ESTADOS_CITA = [
        ('programada', 'Programada'),
        ('en_proceso', 'En Proceso'),
        ('completada', 'Completada'),
        ('cancelada', 'Cancelada'),
    ]

    cliente = models.ForeignKey(Clientes, on_delete=models.CASCADE)
    manicurista = models.ForeignKey(Manicurista, on_delete=models.CASCADE)
    servicios = models.ForeignKey(Servicios, on_delete=models.CASCADE)
    fecha = models.DateField()
    hora = models.TimeField()
    total = models.IntegerField()

    # Valores económicos de la cita
    precio_original = models.IntegerField(
        null=True,
        blank=True,
        help_text="Precio del servicio antes del descuento"
    )

    descuento_aplicado = models.IntegerField(
        default=0,
        help_text="Valor del descuento aplicado a la cita"
    )

    descuento = models.ForeignKey(
        "Descuentos",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas"
    )

    descuento_anio_uso = models.PositiveIntegerField(
    null=True,
    blank=True,
    editable=False
    )

    estado = models.CharField(max_length=20, choices=ESTADOS_CITA, default='programada')


    class Meta:
        constraints = [
            # Evita dos citas de una manicurista a la misma hora.
            models.UniqueConstraint(
                fields=["manicurista", "fecha", "hora"],
                name="unique_manicurista_fecha_hora"
            ),

            # Una clienta no puede reservar dos veces la misma promoción
            # mientras la cita anterior no esté cancelada.
            models.UniqueConstraint(
                fields=["cliente", "descuento"],
                condition=(
                    models.Q(descuento__isnull=False)
                    & ~models.Q(estado="cancelada")
                ),
                name="unique_cliente_descuento_activo"
            ),

            # Una clienta solo puede reservar un descuento de cumpleaños
            # por año. Las citas canceladas liberan el beneficio.
            models.UniqueConstraint(
                fields=["cliente", "descuento_anio_uso"],
                condition=(
                    models.Q(descuento_anio_uso__isnull=False)
                    & ~models.Q(estado="cancelada")
                ),
                name="unique_cliente_descuento_anio"
            ),
        ]


    @property
    def tiene_pago(self):
        # Asumiendo que Pagos tiene un OneToOneField o ForeignKey a Citas
        return hasattr(self, 'pagos') or hasattr(self, 'pago')

    def __str__(self):
        return f"{self.id} - {self.cliente.nombre} {self.cliente.apellido} - {self.fecha} {self.hora} {self.estado}"

class Resena(models.Model):
    cita = models.OneToOneField(Citas, on_delete=models.CASCADE, related_name='resena')
    calificacion = models.IntegerField(choices=[(i, str(i)) for i in range(1, 6)]) # Del 1 al 5
    comentario = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reseña de {self.cita.cliente.nombre} {self.cita.cliente.apellido} - Calificación: {self.calificacion} - Comentario: {self.comentario if self.comentario else 'Sin comentario'}"

class Descuentos(models.Model):
    class Tipo(models.TextChoices):
        CUMPLEAÑOS = 'CUMPLEAÑOS', 'Cumpleaños'
        PRIMERA_CITA = 'PRIMERA_CITA', 'Primera Cita'
        FECHA_ESPECIAL = 'FECHA_ESPECIAL', 'Fecha Especial'
        TEMPORADA = 'TEMPORADA', 'Temporada'
        PERSONALIZADO = 'PERSONALIZADO', 'Promoción del Administrador'

    class TipoBeneficio(models.TextChoices):
        PORCENTAJE = 'PORCENTAJE', 'Porcentaje'
        VALOR_FIJO = 'VALOR_FIJO', 'Valor Fijo'

    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)

    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.PERSONALIZADO
    )

    tipo_beneficio = models.CharField(
        max_length=15,
        choices=TipoBeneficio.choices,
        default=TipoBeneficio.PORCENTAJE
    )

    valor = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(0.01),
        ]
    )

    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()

    activo = models.BooleanField(default=True)

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha_inicio", "nombre"]
        verbose_name = "Descuento"
        verbose_name_plural = "Descuentos"

    
    def clean(self):
        super().clean()

        # Validar que la fecha final no sea anterior a la inicial.
        if self.fecha_inicio and self.fecha_fin:
            if self.fecha_fin < self.fecha_inicio:
                raise ValidationError({
                    "fecha_fin": (
                        "La fecha final no puede ser anterior a la fecha inicial."
                    )
                })

        # Validar que el valor sea positivo.
        if self.valor is not None and self.valor <= 0:
            raise ValidationError({
                "valor": "El valor del descuento debe ser mayor que cero."
            })

        # Validar que el porcentaje no supere el 100 %.
        if (
            self.tipo_beneficio == self.TipoBeneficio.PORCENTAJE
            and self.valor is not None
            and self.valor > 100
        ):
            raise ValidationError({
                "valor": "El porcentaje no puede superar el 100 %."
            })


    @property
    def vigente(self):
        hoy = timezone.localdate()
        return (
            self.activo
            and self.fecha_inicio <= hoy
            and self.fecha_fin >= hoy
        )

    def __str__(self):
        return f"{self.nombre} - {self.valor}"


class Inventario(models.Model):
    CATEGORIAS = [
        ('Esmaltes y Geles', 'Esmaltes y Geles'),
        ('Sistemas Artificiales', 'Sistemas Artificiales'),
        ('Herramientas', 'Herramientas'),
        ('Decoraciones', 'Decoraciones'),
        ('Preparadores', 'Preparadores'),
    ]
    nombre = models.CharField(max_length=100)
    categoria = models.CharField(max_length=50, choices=CATEGORIAS, default='Esmaltes', blank=True, null=True)
    cantidad = models.IntegerField()
    stock_minimo = models.IntegerField()
    imagen = models.ImageField(upload_to='inventario/', blank=True, null=True)

    @property
    def estado_stock(self):
        if self.cantidad == 0:
            return "Agotado"
        elif self.cantidad <= self.stock_minimo:
            return "Stock bajo"
        return "Stock suficiente"


    def __str__(self):
        return f"{self.nombre} - {self.cantidad} "

class MovimientoInventario(models.Model):
    TIPO_MOVIMIENTO = (
        ("Entrada", "ENTRADA"),
        ("Salida", "SALIDA"),
    )
    producto = models.ForeignKey(Inventario, on_delete=models.CASCADE, related_name="movimientos")
    tipo = models.CharField(max_length=10, choices=TIPO_MOVIMIENTO)
    cantidad = models.IntegerField()
    motivo = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tipo} - {self.producto.nombre} ({self.cantidad})"


class Pagos(models.Model):
    ESTADOS =(
        ("Pendiente","PENDIENTE"),
        ("Realizado","REALIZADO"),
        ("Fallido","FALLIDO"),

    )
    METODOS =(
        ("Efectivo","EFECTIVO"),
        ("Nequi","NEQUI"),
        ("Bancolombia", "BANCOLOMBIA"),
        ("Transferencia","TRANSFERENCIA"),

    )
    citas = models.ForeignKey(Citas, on_delete=models.CASCADE, related_name="pagos")
    fecha_pago = models.DateField(auto_now_add=True)
    metodo_pago = models.CharField(
        max_length=50,
        choices=METODOS,
    )
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="Pendiente"
    )
    valor = models.IntegerField()
    referencia = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    def __str__(self):
        return f"Pago #{self.id} - Cita #{self.citas.id} - {self.estado}"

class Recibo(models.Model):
    pago = models.OneToOneField(Pagos, on_delete=models.CASCADE, related_name="recibo")
    fecha_emision = models.DateTimeField(auto_now_add=True)
    detalle = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Recibo #{self.id} (Pago #{self.pago.id if self.pago else 'N/A'})"

class Gastos(models.Model):
    concepto = models.CharField(max_length=100)
    valor = models.IntegerField()
    fecha = models.DateField()
    descripcion = models.TextField()

    def __str__(self):
        return f"{self.concepto} - {self.valor}"


class Administrador(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="administrador"
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(max_length=100)
    password = models.CharField(max_length=100)
    foto_perfil = models.ImageField(upload_to='perfiles/', null=True, blank=True)

    def __str__(self):
        return f"{self.id} - {self.nombre} {self.apellido}"

class SolicitudSoporte(models.Model):

    ESTADOS = (
        ("Pendiente", "Pendiente"),
        ("En revisión", "En revisión"),
        ("Resuelto", "Resuelto"),
    )

    usuario = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitudes_soporte"
    )

    nombre_solicitante = models.CharField(max_length=200)
    rol_solicitante = models.CharField(max_length=50)

    asunto = models.CharField(max_length=200)
    descripcion = models.TextField()

    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="Pendiente"
    )

    respuesta = models.TextField(
        null=True,
        blank=True
    )

    administrador_respuesta = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="respuestas_soporte"
    )

    fecha_creacion = models.DateTimeField(auto_now_add=True)

    fecha_resolucion = models.DateTimeField(
        null=True,
        blank=True
    )

    def __str__(self):
        return f"#{self.id:04d} - {self.asunto}"


class PreferenciasUsuario(models.Model):
    """Preferencias personales de cada usuario de Spa Deseo."""

    FORMATO_FECHA_CHOICES = [
        ("DMY", "DD/MM/AAAA"),
        ("MDY", "MM/DD/AAAA"),
    ]

    FORMATO_HORA_CHOICES = [
        ("12", "12 horas (AM/PM)"),
        ("24", "24 horas"),
    ]

    TAMANO_TEXTO_CHOICES = [
        ("normal", "Normal"),
        ("grande", "Grande"),
        ("pequeno", "Pequeño"),
    ]

    CONTRASTE_CHOICES = [
        ("estandar", "Estándar"),
        ("alto", "Alto contraste"),
    ]

    ANIMACIONES_CHOICES = [
        ("activadas", "Habilitadas"),
        ("reducidas", "Reducir animaciones"),
    ]

    MODO_LECTURA_CHOICES = [
        ("desactivado", "Desactivado"),
        ("activado", "Activado"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferencias_spa"
    )

    verificacion_adicional = models.BooleanField(default=True)
    recordatorios_whatsapp = models.BooleanField(default=True)
    permitir_comunicaciones = models.BooleanField(default=True)

    formato_fecha = models.CharField(
        max_length=3,
        choices=FORMATO_FECHA_CHOICES,
        default="DMY"
    )

    formato_hora = models.CharField(
        max_length=2,
        choices=FORMATO_HORA_CHOICES,
        default="12"
    )

    idioma = models.CharField(
        max_length=10,
        default="es"
    )

    tamano_texto = models.CharField(
        max_length=10,
        choices=TAMANO_TEXTO_CHOICES,
        default="normal"
    )

    contraste = models.CharField(
        max_length=10,
        choices=CONTRASTE_CHOICES,
        default="estandar"
    )

    animaciones = models.CharField(
        max_length=10,
        choices=ANIMACIONES_CHOICES,
        default="activadas"
    )

    modo_lectura = models.CharField(
        max_length=12,
        choices=MODO_LECTURA_CHOICES,
        default="desactivado"
    )

    fecha_actualizacion = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferencias de {self.user.username}"

    class Meta:
        verbose_name = "Preferencia de usuario"
        verbose_name_plural = "Preferencias de usuarios"


class Notificacion(models.Model):

    class Tipo(models.TextChoices):
        CITA_AGENDADA = "CITA_AGENDADA", "Cita agendada"
        RECORDATORIO = "RECORDATORIO", "Recordatorio de cita"
        CITA_CANCELADA = "CITA_CANCELADA", "Cita cancelada"
        CITA_MODIFICADA = "CITA_MODIFICADA", "Cita modificada"
        RECIBO_DISPONIBLE = "RECIBO_DISPONIBLE", "Recibo disponible"
        RESENA_PENDIENTE = "RESENA_PENDIENTE", "Reseña pendiente"
        INVENTARIO_BAJO = "INVENTARIO_BAJO", "Inventario bajo"
        PAGO = "PAGO", "Notificación de pago"
        SOPORTE = "SOPORTE", "Solicitud de soporte"
        GENERAL = "GENERAL", "General"

    destinatario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notificaciones"
    )

    titulo = models.CharField(max_length=150)
    mensaje = models.TextField()

    tipo = models.CharField(
        max_length=30,
        choices=Tipo.choices,
        default=Tipo.GENERAL
    )

    url = models.CharField(
        max_length=255,
        blank=True,
        default=""
    )

    cita = models.ForeignKey(
        Citas,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notificaciones"
    )

    

    leida = models.BooleanField(default=False)

    fecha_creacion = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"

    def __str__(self):
        return f"{self.titulo} - {self.destinatario.username}"


class MensajeContacto(models.Model):
    nombre = models.CharField(max_length=120)
    correo = models.EmailField()
    asunto = models.CharField(max_length=200)
    mensaje = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.nombre} - {self.asunto}"


