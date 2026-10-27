# Importamos los modelos de la base de datos

from .models import (
    Clientes,
    Manicurista,
    Administrador,
    Servicios,
    Citas,
    Inventario,
    MovimientoInventario,
    Pagos,
    Recibo,
    Gastos,
    Resena,
)


# Importamos la librería
from rest_framework import serializers



# Creamos una clase tipo serializador, para mapear nuestro modelo

class ClientesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clientes
        fields = [
            "id",
            "nombre",
            "apellido",
            "telefono",
            "email",
            "fecha_nacimiento",
            "foto_perfil",
        ]
        read_only_fields = ["id", "email", "foto_perfil"]


class ManicuristaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Manicurista
        fields = ["id", "nombre", "apellido", "telefono", "email", "especialidad", "fecha_ingreso", "estado"]

class AdministradorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Administrador
        fields = ["id", "nombre", "apellido", "telefono", "email"]

class ServiciosSerializer(serializers.ModelSerializer):
    class Meta:
        model = Servicios
        fields = '__all__'

class CitasSerializer(serializers.ModelSerializer):
    cliente = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Citas
        fields = '__all__'
        read_only_fields = (
            'id',
            'cliente',
            'precio_original',
            'descuento_aplicado',
            'descuento',
            'descuento_anio_uso',
            'estado',
        )

    def validate(self, attrs):
        manicurista = attrs.get('manicurista')
        servicio = attrs.get('servicios')
        fecha = attrs.get('fecha')
        hora = attrs.get('hora')

        if servicio and servicio.estado != 'Activo':
            raise serializers.ValidationError({
                'servicios': 'Este servicio no está disponible.'
            })

        if manicurista and manicurista.estado != 'Activa':
            raise serializers.ValidationError({
                'manicurista': 'Esta manicurista no está disponible.'
            })

        if fecha and hora and manicurista:
            citas_ocupadas = Citas.objects.filter(
                manicurista=manicurista,
                fecha=fecha,
                hora=hora,
            ).exclude(estado='cancelada')

            if self.instance:
                citas_ocupadas = citas_ocupadas.exclude(
                    pk=self.instance.pk
                )

            if citas_ocupadas.exists():
                raise serializers.ValidationError({
                    'hora': 'La manicurista ya tiene una cita en ese horario.'
                })

        return attrs

class InventarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inventario
        fields = '__all__'

class MovimientoInventarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = MovimientoInventario
        fields = '__all__'

class PagosSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pagos
        fields = '__all__'

class ReciboSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recibo
        fields = '__all__'


class GastosSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gastos
        fields = '__all__'


class ResenaSerializer(serializers.ModelSerializer):
    cita = serializers.PrimaryKeyRelatedField(
        queryset=Citas.objects.all()
    )

    servicio_nombre = serializers.CharField(
        source='cita.servicios.nombre',
        read_only=True
    )

    fecha_cita = serializers.DateField(
        source='cita.fecha',
        read_only=True
    )

    class Meta:
        model = Resena
        fields = [
            'id',
            'cita',
            'servicio_nombre',
            'fecha_cita',
            'calificacion',
            'comentario',
            'fecha_creacion',
        ]
        read_only_fields = ['id', 'fecha_creacion']

    def validate(self, attrs):
        request = self.context.get('request')
        cita = attrs.get('cita')

        if request and cita:
            if cita.cliente.user_id != request.user.id:
                raise serializers.ValidationError({
                    'cita': 'No puedes reseñar una cita de otra clienta.'
                })

            if (cita.estado or '').strip().lower() != 'completada':
                raise serializers.ValidationError({
                    'cita': 'Solo puedes reseñar citas completadas.'
                })

                            # Evitar que una cita tenga más de una reseña.

            if Resena.objects.filter(cita=cita).exists():
                raise serializers.ValidationError({
                    'cita': 'Esta cita ya tiene una reseña registrada.'
                })

        return attrs
