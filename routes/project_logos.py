from fastapi import APIRouter, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from config.database import db_dependency
from schemas.project import ProjectLogoUpdate, ProjectPublic
from utils.auth import user_dependency
from utils.images import read_image
from utils.project_logos import remove_project_logo, set_project_logo
from utils.projects import build_access

project_logos_router = APIRouter(tags=["projects"])

_SESSION_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {
        "description": (
            "El usuario no es un privilegiado del proyecto o no es profesor del curso"
        )
    },
    404: {"description": "No existe el proyecto o la imagen"},
    409: {
        "description": (
            "El proyecto está en un estado final o la imagen ya es logo de otro proyecto"
        )
    },
}


def _parse_error(message: str, loc: list[str]) -> RequestValidationError:
    return RequestValidationError(
        [{"type": "value_error", "loc": loc, "msg": message, "input": None}]
    )


async def _parse_logo(request: Request):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type == "multipart/form-data":
        form = await request.form()
        extra = [key for key in form.keys() if key != "file"]
        if extra:
            raise _parse_error("Extra inputs are not permitted", ["body", extra[0]])
        file = form.get("file")
        if not isinstance(file, StarletteUploadFile):
            raise _parse_error("file is required", ["body", "file"])
        return await read_image(file), file.filename, None

    try:
        payload = await request.json()
    except Exception as exc:
        raise _parse_error("Invalid JSON", ["body"]) from exc
    try:
        data = ProjectLogoUpdate.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    return None, None, data.id_image


@project_logos_router.put(
    "/projects/{id_project}/logo",
    response_model=ProjectPublic,
    summary="Subir o reemplazar el logo de un proyecto",
    responses={
        **_SESSION_ERRORS,
        413: {"description": "El archivo supera el tamaño máximo (5 MB)"},
        422: {
            "description": (
                "Archivo vacío o inválido, formato no soportado o body inválido"
            )
        },
    },
)
async def set_project_logo_route(
    id_project: int,
    request: Request,
    db: db_dependency,
    user: user_dependency,
):
    """
    Asocia o reemplaza el logo del proyecto. **Privilegiados del proyecto**, solo
    mientras no esté en un estado final.

    Acepta `multipart/form-data` con `file` (jpeg, png o webp, máximo 5 MB) o
    JSON con `id_image` de una imagen ya subida. Una imagen no puede ser logo de
    dos proyectos. Al reemplazar, la imagen anterior se elimina si ya no está en
    uso.
    """
    file_data, file_name, id_image = await _parse_logo(request)
    access = await build_access(db, user)
    return await set_project_logo(
        db,
        access,
        id_project,
        file_data=file_data,
        file_name=file_name,
        id_image=id_image,
    )


@project_logos_router.delete(
    "/projects/{id_project}/logo",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar el logo de un proyecto",
    responses=_SESSION_ERRORS,
)
async def delete_project_logo_route(
    id_project: int,
    db: db_dependency,
    user: user_dependency,
):
    """
    Quita el logo del proyecto. **Privilegiados del proyecto**, solo mientras no
    esté en un estado final. La imagen se elimina si no está siendo usada por una
    tecnología.
    """
    access = await build_access(db, user)
    await remove_project_logo(db, access, id_project)
