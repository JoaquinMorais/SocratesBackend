import hashlib
import re
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError
from sqlmodel import select

from config.settings import settings
from models import Image, Technology
from schemas.image import ImagePublic
from utils import storage

# Formatos de entrada aceptados; el archivo guardado es siempre WebP.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
# Límite de píxeles para evitar "decompression bombs" con imágenes gigantes.
PILImage.MAX_IMAGE_PIXELS = 25_000_000

_TOO_LARGE = HTTPException(
    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image is too large"
)
_EMPTY = HTTPException(
    status.HTTP_422_UNPROCESSABLE_ENTITY, "The file is empty"
)
_CHUCK = 1_048_576  # 1 MB por lectura


def _invalid_image() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "The file is not a valid image"
    )


async def read_image(file: UploadFile, *, max_bytes: int | None = None) -> bytes:
    """Lee el archivo subido en bloques, cortando apenas supera el máximo."""
    limit = max_bytes if max_bytes is not None else settings.IMAGE_MAX_BYTES
    parts = bytearray()
    while True:
        chunk = await file.read(_CHUCK)
        if not chunk:
            break
        parts.extend(chunk)
        if len(parts) > limit:
            raise _TOO_LARGE
    return bytes(parts)


def _sanitize_name(original: str | None) -> str | None:
    if not original:
        return None
    # Solo el nombre del archivo, sin separadores ni caracteres de control.
    name = original.replace("\\", "/").rsplit("/", 1)[-1].replace("\x00", "")
    name = re.sub(r"\s+", " ", name).strip()
    return name[:255] or None


def _convert_to_webp(data: bytes) -> bytes:
    """Convierte la imagen a WebP; rechaza formatos o archivos inválidos."""
    try:
        img = PILImage.open(BytesIO(data))
        img.load()
    except (DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise _invalid_image() from exc
    if (img.format or "").upper() not in ALLOWED_FORMATS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only jpeg, png or webp images are supported",
        )
    # Corrige la orientación según EXIF antes de convertir.
    img = ImageOps.exif_transpose(img)
    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )
    buf = BytesIO()
    img.convert("RGBA" if has_alpha else "RGB").save(
        buf, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY, method=6
    )
    return buf.getvalue()


async def prepare_image(data: bytes, original_name: str | None) -> tuple[Image, bytes]:
    """Valida y convierte; devuelve la fila sin guardar (y el WebP) para que el
    llamador la escriba dentro de su propia transacción."""
    if len(data) > settings.IMAGE_MAX_BYTES:
        raise _TOO_LARGE
    if not data:
        raise _EMPTY
    webp = await run_in_threadpool(_convert_to_webp, data)
    image = Image(
        key=storage.new_key(),
        original_name=_sanitize_name(original_name),
        content_type="image/webp",
        size_bytes=len(webp),
        checksum=hashlib.sha256(webp).hexdigest(),
    )
    return image, webp


async def save_image(db, data: bytes, original_name: str | None) -> Image:
    """Sube y guarda una imagen: disco + fila. Si algo falla, limpia el archivo."""
    image, webp = await prepare_image(data, original_name)
    try:
        storage.save_file(image.key, webp)
        db.add(image)
        await db.commit()
    except Exception:
        await db.rollback()
        storage.delete_file(image.key)
        raise
    return image


def to_public(image: Image) -> ImagePublic:
    return ImagePublic(
        id_image=image.id_image,
        url=storage.public_url(image.key),
        original_name=image.original_name,
        content_type=image.content_type,
        size_bytes=image.size_bytes,
        created_at=image.created_at,
    )


async def get_image(db, id_image: int) -> Image:
    image = await db.get(Image, id_image)
    if not image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    return image


def image_in_use(db, id_image: int, *, exclude_technology: int | None = None):
    """Consulta para saber si una imagen está asignada a alguna tecnología."""
    conditions = [Technology.id_image == id_image]
    if exclude_technology is not None:
        conditions.append(Technology.id_technology != exclude_technology)
    return (
        select(Technology.id_technology).where(*conditions).limit(1)
    )


async def delete_image(db, image: Image) -> None:
    """Borra la fila y el archivo; el archivo se borra tras el commit."""
    taken = (await db.exec(image_in_use(db, image.id_image))).first()
    if taken is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Image is in use by a technology"
        )
    await db.delete(image)
    await db.commit()
    storage.delete_file(image.key)
