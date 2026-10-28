from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from config.database import db_dependency
from schemas.image import ImagePublic
from utils.auth import user_dependency
from utils.images import delete_image, get_image, read_image, save_image, to_public
from utils.permissions import professor_dependency

images_router = APIRouter(prefix="/images", tags=["images"])

_READ_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}
_WRITE_ERRORS = {
    **_READ_ERRORS,
    403: {"description": "El usuario no es profesor ni super admin"},
}
_NOT_FOUND = {404: {"description": "No existe la imagen"}}


@images_router.post(
    "",
    response_model=ImagePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Subir una imagen",
    responses={
        **_WRITE_ERRORS,
        413: {"description": "El archivo supera el tamaño máximo (5 MB)"},
        422: {
            "description": (
                "El archivo está vacío, no es una imagen válida o su formato "
                "no es jpeg, png ni webp"
            )
        },
    },
)
async def create_image_route(
    db: db_dependency,
    _: professor_dependency,
    file: Annotated[
        UploadFile,
        File(description="Archivo jpeg, png o webp (se convierte a WebP)"),
    ],
):
    """
    Sube una imagen. **Profesores y super admin.**

    - Se acepta `multipart/form-data` con el archivo en el campo `file`.
    - El archivo se guarda **siempre como WebP** (máximo 5 MB, calidad 85);
      la orientación EXIF se corrige y los metadatos se descartan.
    - Devuelve la `url` pública del archivo y sus datos; si no se asocia a
      una tecnología, queda disponible para vincularla después con
      `POST /technologies` o `PATCH /technologies/{id}` usando `id_image`.
    """
    data = await read_image(file)
    image = await save_image(db, data, file.filename)
    return to_public(image)


@images_router.get(
    "/{id_image}",
    response_model=ImagePublic,
    summary="Consultar una imagen",
    responses={**_READ_ERRORS, **_NOT_FOUND},
)
async def get_image_route(id_image: int, db: db_dependency, _: user_dependency):
    """Devuelve los datos de una imagen (url, tamaño, nombre original). **Cualquier usuario logueado.**"""
    return to_public(await get_image(db, id_image))


@images_router.delete(
    "/{id_image}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una imagen",
    responses={
        **_WRITE_ERRORS,
        **_NOT_FOUND,
        409: {"description": "La imagen está asignada a una tecnología"},
    },
)
async def delete_image_route(id_image: int, db: db_dependency, _: professor_dependency):
    """
    Elimina una imagen y su archivo. **Profesores y super admin.**

    Responde **409** si alguna tecnología la está usando; primero hay que
    quitarla de esa tecnología (`DELETE /technologies/{id}/image`).
    """
    await delete_image(db, await get_image(db, id_image))
