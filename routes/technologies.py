from typing import Annotated

from fastapi import APIRouter, File, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from config.database import db_dependency
from schemas.technology import (
    TechnologyCreate,
    TechnologyList,
    TechnologyPublic,
    TechnologyUpdate,
)
from utils.auth import user_dependency
from utils.images import read_image
from utils.permissions import professor_dependency
from utils.technologies import (
    create_technology,
    delete_technology,
    get_technology,
    list_technologies,
    remove_technology_image,
    set_technology_image,
    to_public,
    update_technology,
)

technologies_router = APIRouter(prefix="/technologies", tags=["technologies"])

_READ_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}
_WRITE_ERRORS = {
    **_READ_ERRORS,
    403: {"description": "El usuario no es profesor ni super admin"},
}
_NOT_FOUND = {404: {"description": "No existe la tecnología"}}

_FILE_ERRORS = {
    413: {"description": "El archivo supera el tamaño máximo (5 MB)"},
    422: {
        "description": (
            "El archivo está vacío, no es una imagen válida o su formato no es "
            "jpeg, png ni webp"
        )
    },
}

_KNOWN_FIELDS = {"name", "description", "file"}


def _json_invalid() -> RequestValidationError:
    return RequestValidationError(
        [{"type": "json_invalid", "loc": ["body"], "msg": "Invalid JSON", "input": None}]
    )


async def _parse_body(
    request: Request, model: type[TechnologyCreate | TechnologyUpdate]
):
    """Acepta `application/json` o `multipart/form-data` en la misma ruta.

    Devuelve `(schema, archivo)`: el schema se valida con Pydantic
    (los errores se elevan como 422) y `archivo` es un `UploadFile` opcional.
    """
    kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if kind == "multipart/form-data":
        form = await request.form()
        found: dict[str, object] = {}
        for key, value in form.multi_items():
            found[key] = value
        extra = [key for key in found if key not in _KNOWN_FIELDS]
        if extra:
            raise RequestValidationError(
                [
                    {
                        "type": "extra_forbidden",
                        "loc": ["body", key],
                        "msg": "Extra inputs are not permitted",
                        "input": None,
                    }
                    for key in extra
                ]
            )
        file = found.get("file")
        if file is not None and not isinstance(file, StarletteUploadFile):
            raise RequestValidationError(
                [{"type": "invalid_input", "loc": ["body", "file"], "msg": "Expected an uploaded file", "input": None}]
            )
        fields = {key: found[key] for key in (_KNOWN_FIELDS - {"file"}) if key in found}
        try:
            return model.model_validate(fields), file
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from None

    # JSON (con o sin header exacto): el body se comporta igual que antes.
    try:
        payload = await request.json()
    except Exception:
        raise _json_invalid() from None
    try:
        return model.model_validate(payload), None
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from None


def _multipart_docs(model_name: str, required: bool) -> dict:
    """Documentación OpenAPI con los dos content-types posibles de la ruta."""
    return {
        "requestBody": {
            "required": required,
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{model_name}"}
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "example": "React"},
                            "description": {"type": "string", "nullable": True},
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "Imagen jpeg, png o webp (se convierte a WebP)",
                            },
                        },
                    }
                },
            },
        }
    }


@technologies_router.post(
    "",
    response_model=TechnologyPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una tecnología",
    openapi_extra=_multipart_docs("TechnologyCreate", True),
    responses={
        **_WRITE_ERRORS,
        **_FILE_ERRORS,
        409: {"description": "Ya existe una tecnología con ese nombre, o su imagen ya está asignada a otra"},
    },
)
async def create_technology_route(request: Request, db: db_dependency, _: professor_dependency):
    """
    Crea una tecnología. **Profesores y super admin.**

    Se acepta `application/json` o `multipart/form-data`:

    - **JSON**: `name` (obligatorio, sin espacios sobrantes, no se repite sin
      distinguir mayúsculas: `React` y `react` son la misma), `description`
      (opcional, máximo 500) y `id_image` opcional: el id de una imagen ya
      subida con `POST /images` (404 si no existe, 409 si está en otra
      tecnología).
    - **multipart**: `name`, `description` y `file` opcional; si se envía el
      archivo se guarda como WebP (máximo 5 MB) y queda asociada. Es todo o
      nada: si el alta falla, no queda ni la tecnología ni el archivo.

    La respuesta incluye `image` (objeto con la `url` del archivo) o `null`.
    """
    data, file = await _parse_body(request, TechnologyCreate)
    file_data = await read_image(file) if file is not None else None
    return to_public(await create_technology(db, data, file_data=file_data, file_name=file.filename if file else None))


@technologies_router.get(
    "",
    response_model=TechnologyList,
    summary="Listar tecnologías",
    responses=_READ_ERRORS,
)
async def get_technologies(
    db: db_dependency,
    _: user_dependency,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Busca dentro del nombre"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista las tecnologías ordenadas por nombre. **Cualquier usuario logueado.**

    Está paginado: `total` es la cantidad de tecnologías que cumple el filtro.
    """
    items, total = await list_technologies(db, q=q, limit=limit, offset=offset)
    return TechnologyList(
        items=[to_public(t) for t in items], total=total, limit=limit, offset=offset
    )


@technologies_router.get(
    "/{id_technology}",
    response_model=TechnologyPublic,
    summary="Consultar una tecnología",
    responses={**_READ_ERRORS, **_NOT_FOUND},
)
async def get_technology_route(
    id_technology: int, db: db_dependency, _: user_dependency
):
    """Devuelve una tecnología por su id. **Cualquier usuario logueado.**"""
    return to_public(await get_technology(db, id_technology))


@technologies_router.patch(
    "/{id_technology}",
    response_model=TechnologyPublic,
    summary="Modificar una tecnología",
    openapi_extra=_multipart_docs("TechnologyUpdate", False),
    responses={
        **_WRITE_ERRORS,
        **_NOT_FOUND,
        **_FILE_ERRORS,
        409: {
            "description": "Ya existe otra tecnología con ese nombre, o la imagen pedida ya está asignada a otra"
        },
    },
)
async def update_technology_route(
    id_technology: int, request: Request, db: db_dependency, _: professor_dependency
):
    """
    Modifica una tecnología. **Profesores y super admin.** Se envían solo los
    campos que cambian (en JSON o multipart).

    - **JSON**: `name`, `description`, `id_image`. `name` no admite `null`;
      `description: null` limpia el campo. `id_image` reemplaza la imagen
      actual (que se borra de la BD y del disco); para desasociarla sin
      reemplazarla, usar `DELETE /technologies/{id}/image` (un `null` no
      desasocia).
    - **multipart**: `name`, `description` y `file`; con `file` se sube y
      queda asociada la nueva imagen (la anterior se borra). Un PATCH solo
      con `file` es válido.

    Cambiar el casing del nombre (por ejemplo `react` a `React`) está permitido
    porque la unicidad no distingue mayúsculas.
    """
    data, file = await _parse_body(request, TechnologyUpdate)
    file_data = await read_image(file) if file is not None else None
    return to_public(
        await update_technology(db, id_technology, data, file_data=file_data, file_name=file.filename if file else None)
    )


@technologies_router.put(
    "/{id_technology}/image",
    response_model=TechnologyPublic,
    summary="Subir o reemplazar la imagen de una tecnología",
    responses={
        **_WRITE_ERRORS,
        **_NOT_FOUND,
        **_FILE_ERRORS,
    },
)
async def set_technology_image_route(
    id_technology: int,
    db: db_dependency,
    _: professor_dependency,
    file: Annotated[UploadFile, File(description="Archivo jpeg, png o webp (se convierte a WebP)")],
):
    """
    Sube y asigna la imagen de una tecnología. **Profesores y super admin.**

    Se guarda el archivo (siempre WebP, máximo 5 MB) y queda asociado a esta
    tecnología; si ya tenía imagen, la anterior se **borra** (fila y archivo).
    Responde con la tecnología actualizada.
    """
    data = await read_image(file)
    return to_public(
        await set_technology_image(db, id_technology, file_data=data, file_name=file.filename)
    )


@technologies_router.delete(
    "/{id_technology}/image",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar la imagen de una tecnología",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe la tecnología o no tiene imagen"},
    },
)
async def remove_technology_image_route(
    id_technology: int, db: db_dependency, _: professor_dependency
):
    """
    Quita la imagen de una tecnología y la **borra** (fila y archivo).
    **Profesores y super admin.** Si no tiene imagen, responde **404**.
    """
    await remove_technology_image(db, id_technology)


@technologies_router.delete(
    "/{id_technology}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una tecnología",
    responses={
        **_WRITE_ERRORS,
        **_NOT_FOUND,
        409: {"description": "La tecnología está en uso por un proyecto"},
    },
)
async def delete_technology_route(
    id_technology: int, db: db_dependency, _: professor_dependency
):
    """
    Elimina una tecnología. **Profesores y super admin.**

    Responde **409** si algún proyecto la tiene asociada; primero hay que
    quitarla de esos proyectos. Su imagen (si tiene) se borra también.
    """
    await delete_technology(db, id_technology)
