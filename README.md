# Sistema Integral de Gestión y Agendamiento para Spa Deseo

Aplicación web desarrollada en equipo con **Django**, **Tailwind CSS** y **SQLite** para digitalizar y centralizar la operación de **Spa Deseo** que, anteriormente, gestionaba sus citas de manera manual. El sistema integra reservas en línea, autenticación social, gestión de especialistas, facturación en PDF, inventario y contabilidad bajo una arquitectura de **3 roles de usuario**.

## Problema y solución

El manejo manual de citas generaba fricción, pérdida de tiempo y estrés tanto para la administradora como para los clientes. Este proyecto automatiza el flujo completo del negocio: desde que el cliente inicia sesión, elige a su manicurista y agenda su cita, hasta la generación de comprobantes en PDF y el control interno de inventario y finanzas.

## Autenticación y Seguridad

- **Inicio de sesión con Google (OAuth 2.0):** Integración de autenticación social para facilitar el registro e ingreso rápido de los usuarios.
- **Control de acceso basado en roles (RBAC):** Uso del sistema nativo de autenticación, grupos, permisos y perfiles de **Django** para separar las vistas, rutas y funcionalidades entre **Cliente**, **Manicurista** y **Administradora**.
- **Perfiles de usuario personalizados:** Gestión de datos específicos asociados a cada tipo de usuario dentro del sistema.

## Funcionalidades por rol

### Cliente
- Inicio de sesión tradicional o con cuenta de Google.
- Agendamiento de citas en línea según disponibilidad.
- Visualización de citas programadas en calendario.
- Exploración del portafolio de trabajos de las manicuristas.
- Publicación de reseñas sobre el servicio recibido.
- Consulta y **descarga de facturas en formato PDF**.
- Edición de perfil de usuario.

### Manicurista
- Consulta de calendario personal y citas agendadas.
- Visualización de listado de clientes.
- Creación y administración de su **propio portafolio de trabajos**.
- Edición de perfil.

### Administradora
- Acceso a la supervisión operativa de citas, servicios y usuarios.
- **Módulo de Inventario:** Control y gestión de insumos y productos del spa.
- **Módulo de Contabilidad:** Seguimiento financiero e ingresos del negocio.

## Arquitectura y Desarrollo

- **Backend:** Python y Django (configuración de rutas, vistas, lógica de negocio, autenticación por roles, generación de documentos PDF y ORM).
- **Frontend / UI:** HTML, Tailwind CSS y sistema de plantillas de Django para construir interfaces limpias y responsivas adaptadas a cada perfil.
- **Base de datos:** SQLite.

## Instalación y ejecución local

1. **Clonar el repositorio:**
   ```bash
   git clone <URL_DE_TU_REPOSITORIO>
   cd <NOMBRE_DE_LA_CARPETA>
   code .
   ```

**1.1 Tip importante para que `code .` funcione en cualquier equipo**

El comando `code .` depende de que VS Code tenga habilitada la opción de abrirse desde la terminal en la máquina de quien lo ejecuta:

* **En Windows:** al instalar VS Code, la opción *"Add 'code' to PATH"* suele activarse sola; si no funciona, basta con abrir VS Code, presionar `Ctrl + Shift + P`, buscar **`Shell Command: Install 'code' command in PATH`** (o revisar que la ruta de instalación de VS Code esté en las variables de entorno `PATH` de Windows).
* **En macOS:** dentro de VS Code, abre la paleta de comandos con `Cmd + Shift + P` y ejecuta **`Shell Command: Install 'code' command in PATH`**.
* **En Linux:** normalmente queda disponible automáticamente al instalar el paquete oficial de VS Code.


2. **Crear y activar un entorno virtual:**
   ```bash
   python -m venv venv
   # En Windows:
   venv\Scripts\activate
   # En Linux / macOS:
   source venv/bin/activate
   ```

3. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar variables de entorno (Google OAuth y Django):**
   Crea un archivo `.env` en la raíz del proyecto con las credenciales necesarias:
   ```env
   SECRET_KEY=tu_clave_secreta_de_django
   GOOGLE_CLIENT_ID=tu_client_id_de_google
   GOOGLE_CLIENT_SECRET=tu_client_secret_de_google
   ```

5. **Aplicar migraciones de base de datos:**
   ```bash
   python manage.py migrate
   ```

6. **Ejecutar el servidor de desarrollo:**
   ```bash
   python manage.py runserver
   ```
   Abre `http://127.0.0.1:8000/` en tu navegador.


