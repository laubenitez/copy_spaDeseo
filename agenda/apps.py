from django.apps import AppConfig

class TuAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'agenda'

    def ready(self):
        import agenda.signals  # <--- Carga el archivo de señales