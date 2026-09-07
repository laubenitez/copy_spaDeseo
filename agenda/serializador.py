# Importamos los modelos de la base de datos
from .models import *

# Importamos la librería
from rest_framework import serializers



# Creamos una clase tipo serializador, para mapear nuestro modelo
class ClientesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clientes
        fields = ["id", "nombre", "apellido", "telefono", "email", "color_piel"]
        # fields = '__all__'

class ManicuristaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Manicurista
        fields = ["id", "nombre", "apellido", "telefono", "email", "especialidad", "fecha_ingreso", "estado"]

class ServiciosSerializer(serializers.ModelSerializer):
    class Meta:
        model = Servicios
        fields = '__all__'

class CitasSerializer(serializers.ModelSerializer):
    class Meta:
        model = Citas
        fields = '__all__'

class InventarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inventario
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