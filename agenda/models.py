from django.db import models
from django.contrib.auth.models import User

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
    password = models.CharField(max_length=100)
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




class Servicios(models.Model):
    nombre = models.CharField(max_length=100)
    precio = models.IntegerField()
    descripcion = models.TextField(null=True, blank=True)
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
    estado = models.CharField(max_length=20, choices=ESTADOS_CITA, default='programada')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manicurista", "fecha", "hora"],
                name="unique_manicurista_fecha_hora"
            )
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


