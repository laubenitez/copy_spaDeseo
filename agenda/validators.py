from django.core.exceptions import ValidationError
from PIL import Image


MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_IMAGE_WIDTH = 5000
MAX_IMAGE_HEIGHT = 5000

ALLOWED_IMAGE_FORMATS = {
    "JPEG",
    "PNG",
    "WEBP",
}


def validar_imagen_portafolio(imagen):
    """
    Valida las imágenes que se utilizan en el portafolio
    de las manicuristas.
    """

    if not imagen:
        return

    # ==========================================
    # 1. Validar tamaño del archivo
    # ==========================================

    if imagen.size > MAX_IMAGE_SIZE:
        raise ValidationError(
            "La imagen no puede superar los 5 MB."
        )

    # ==========================================
    # 2. Validar que realmente sea una imagen
    # ==========================================

    try:
        imagen.seek(0)

        with Image.open(imagen) as img:

            # ==================================
            # 3. Validar formato real
            # ==================================

            if img.format not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError(
                    "El formato de imagen no está permitido. "
                    "Solo se permiten JPG, PNG y WEBP."
                )

            # ==================================
            # 4. Validar dimensiones
            # ==================================

            width, height = img.size

            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                raise ValidationError(
                    "La imagen no puede superar "
                    "las dimensiones de 5000 x 5000 píxeles."
                )

            # ==================================
            # 5. Verificar que la imagen sea válida
            # ==================================

            img.verify()

    except ValidationError:
        raise

    except Exception:
        raise ValidationError(
            "El archivo seleccionado no es una imagen válida."
        )

    finally:
        try:
            imagen.seek(0)
        except Exception:
            pass