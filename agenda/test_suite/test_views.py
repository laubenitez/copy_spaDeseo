from django.test import TestCase
from django.contrib.auth.models import User
from datetime import date, time, timedelta
from agenda.models import Rol, PerfilUsuario, Clientes, Manicurista, Servicios, Citas


class LandingPageTest(TestCase):

    def test_landing_page_carga_correctamente(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)


class RegistroTest(TestCase):

    def setUp(self):
        self.rol_cliente = Rol.objects.create(
            nombre="CLIENTE",
            descripcion="Cliente del spa"
        )

    def test_registro_cliente_exitoso(self):

        datos = {
            "nombre": "Laura",
            "apellido": "Prueba",
            "email": "laura_test@example.com",
            "telefono": "3001234567",
            "password": "Laura1234!"
        }

        response = self.client.post(
            "/register/",
            datos
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            User.objects.filter(
                username="laura_test@example.com"
            ).exists()
        )

        user = User.objects.get(
            username="laura_test@example.com"
        )

        self.assertTrue(
            user.check_password("Laura1234!")
        )

        perfil = PerfilUsuario.objects.get(user=user)

        self.assertEqual(
            perfil.rol.nombre,
            "CLIENTE"
        )

        self.assertTrue(
            Clientes.objects.filter(
                user=user,
                nombre="Laura",
                apellido="Prueba",
                email="laura_test@example.com"
            ).exists()
        )

    def test_registro_con_correo_duplicado(self):

        User.objects.create_user(
            username="laura_test@example.com",
            email="laura_test@example.com",
            password="Laura1234!"
        )

        datos = {
            "nombre": "Otra",
            "apellido": "Persona",
            "email": "laura_test@example.com",
            "telefono": "3009876543",
            "password": "Otra1234!"
        }

        response = self.client.post(
            "/register/",
            datos
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            User.objects.filter(
                username="laura_test@example.com"
            ).count(),
            1
        )


class LoginTest(TestCase):

    def setUp(self):
        self.rol_cliente = Rol.objects.create(
            nombre="CLIENTE",
            descripcion="Cliente del spa"
        )

        self.user = User.objects.create_user(
            username="login_test@example.com",
            email="login_test@example.com",
            password="Login1234!",
            first_name="Laura",
            last_name="Prueba"
        )

        self.perfil = PerfilUsuario.objects.get(user=self.user)
        self.perfil.rol = self.rol_cliente
        self.perfil.save()

   
    def test_login_exitoso(self):

        datos = {
            "user": "login_test@example.com",
            "password": "Login1234!"
        }

        response = self.client.post(
            "/login/",
            datos
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            response.url,
            "/dashboard/"
        )

        self.assertTrue(
            response.wsgi_request.user.is_authenticated
        )

    def test_login_con_contrasena_incorrecta(self):

        datos = {
            "user": "login_test@example.com",
            "password": "ContraseñaIncorrecta123!"
        }

        response = self.client.post(
            "/login/",
            datos
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            response.url,
            "/login/"
        )

        self.assertFalse(
            response.wsgi_request.user.is_authenticated
        )



class CitasTest(TestCase):

    def setUp(self):
        self.rol_cliente = Rol.objects.create(
            nombre="CLIENTE",
            descripcion="Cliente del spa"
        )

        self.user = User.objects.create_user(
            username="cita_test@example.com",
            email="cita_test@example.com",
            password="Cita1234!"
        )

        self.perfil = PerfilUsuario.objects.get(user=self.user)
        self.perfil.rol = self.rol_cliente
        self.perfil.save()

        self.cliente = Clientes.objects.create(
            user=self.user,
            nombre="Laura",
            apellido="Prueba",
            telefono="3001234567",
            email="cita_test@example.com"
        )

        self.manicurista = Manicurista.objects.create(
            nombre="Ana",
            apellido="Prueba",
            telefono="3001112233",
            email="ana@example.com",
            password="Ana1234!",
            especialidad="Uñas",
            fecha_ingreso=date.today(),
            estado="Activa"
        )

        self.servicio = Servicios.objects.create(
            nombre="Manicure",
            precio=30000,
            descripcion="Servicio de manicure",
            estado="Activo",
            duracion=60
        )

    def test_no_permite_cita_solapada(self):

        self.client.login(
            username="cita_test@example.com",
            password="Cita1234!"
        )

        fecha_cita = date.today() + timedelta(days=1)

        Citas.objects.create(
            cliente=self.cliente,
            manicurista=self.manicurista,
            servicios=self.servicio,
            fecha=fecha_cita,
            hora=time(10, 0),
            total=30000,
            estado="programada"
        )

        datos = {
            "manicurista": self.manicurista.id,
            "servicios": self.servicio.id,
            "fecha": fecha_cita.strftime("%Y-%m-%d"),
            "hora": "10:30"
        }

        response = self.client.post(
            "/crear_citas/",
            datos
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            Citas.objects.filter(
                manicurista=self.manicurista,
                fecha=fecha_cita
            ).count(),
            1
        )

class ServiciosTest(TestCase):

    def setUp(self):
        self.rol_cliente = Rol.objects.create(
            nombre="CLIENTE",
            descripcion="Cliente del spa"
        )

        self.user = User.objects.create_user(
            username="servicio_test@example.com",
            email="servicio_test@example.com",
            password="Servicio1234!"
        )

        self.perfil = PerfilUsuario.objects.get(user=self.user)
        self.perfil.rol = self.rol_cliente
        self.perfil.save()

        self.servicio = Servicios.objects.create(
            nombre="Manicure semipermanente",
            precio=45000,
            descripcion="Manicure con esmalte semipermanente",
            estado="Activo",
            duracion=60
        )

    def test_listar_servicios(self):

        self.client.login(
            username="servicio_test@example.com",
            password="Servicio1234!"
        )

        response = self.client.get("/servicios/")

        self.assertEqual(response.status_code, 200)

        self.assertTemplateUsed(
            response,
            "servicios.html"
        )

        self.assertEqual(
            response.context["datos"].count(),
            1
        )

class PermisosTest(TestCase):

    def setUp(self):
        self.rol_cliente = Rol.objects.create(
            nombre="CLIENTE",
            descripcion="Cliente del spa"
        )

        self.rol_admin = Rol.objects.create(
            nombre="ADMINISTRADOR",
            descripcion="Administrador del spa"
        )

        self.user = User.objects.create_user(
            username="permisos_test@example.com",
            email="permisos_test@example.com",
            password="Permisos1234!"
        )

        self.perfil = PerfilUsuario.objects.get(user=self.user)
        self.perfil.rol = self.rol_cliente
        self.perfil.save()

    def test_cliente_no_puede_acceder_a_inventario(self):

        self.client.login(
            username="permisos_test@example.com",
            password="Permisos1234!"
        )

        response = self.client.get("/ver_inventario/")

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            response.url,
            "/dashboard/"
        )

        self.assertTrue(
            response.wsgi_request.user.is_authenticated
        )



