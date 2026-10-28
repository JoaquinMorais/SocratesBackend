import uuid
from pathlib import Path

from config.settings import settings


def new_key() -> str:
    """Clave única dentro del almacenamiento (ej: `images/ab12...webp`)."""
    return f"images/{uuid.uuid4().hex}.webp"


def _root() -> Path:
    return Path(settings.MEDIA_DIR)


def public_url(key: str) -> str:
    """URL pública del archivo: `MEDIA_BASE_URL` + key."""
    return f"{settings.MEDIA_BASE_URL.rstrip('/')}/{key}"


def local_path(key: str) -> Path:
    """Ruta local de la key, garantizando que no escape del directorio raíz."""
    path = (_root() / key).resolve()
    root = _root().resolve()
    if not path.is_relative_to(root):
        raise ValueError("Invalid storage key")
    return path


def save_file(key: str, data: bytes) -> None:
    """Escribe el archivo en disco de forma atómica (temp + rename).

    Es la implementación local del almacenamiento; una futura nube (S3,
    Cloudinary...) solo reemplaza estas funciones, sin tocar la BD ni la API.
    """
    path = local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def delete_file(key: str) -> None:
    """Borra el archivo si existe; no falla si el archivo ya no está."""
    try:
        path = local_path(key)
    except ValueError:
        return  # key inválida: nada que borrar
    path.unlink(missing_ok=True)
