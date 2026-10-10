from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.section import SectionCreate, SectionList, SectionPublic, SectionUpdate
from utils.permissions import super_admin_dependency
from utils.sections import (
    create_section,
    delete_section,
    get_section,
    list_sections,
    to_public,
    update_section,
)

sections_router = APIRouter(prefix="/sections", tags=["sections"])

_AUTH_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no es profesor super admin"},
}
_NOT_FOUND = {404: {"description": "No existe la comisión"}}


@sections_router.post(
    "",
    response_model=SectionPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una comisión",
    responses={
        **_AUTH_ERRORS,
        409: {"description": "Ya existe una comisión con ese nombre"},
        422: {"description": "Nombre vacío, de más de 20 caracteres o campos desconocidos"},
    },
)
async def create_section_route(
    data: SectionCreate, db: db_dependency, _: super_admin_dependency
):
    """
    Crea una comisión (por ejemplo `3K1`). **Solo super admin.**

    El nombre se guarda sin espacios sobrantes y **en mayúsculas** (`3k1` queda
    como `3K1`), y no puede repetirse: `3k1` y `3K1` son la misma comisión.
    Máximo 20 caracteres.
    """
    return to_public(await create_section(db, data))


@sections_router.get(
    "",
    response_model=SectionList,
    summary="Listar comisiones",
    responses=_AUTH_ERRORS,
)
async def get_sections(
    db: db_dependency,
    _: super_admin_dependency,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=20, description="Busca dentro del nombre"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista las comisiones ordenadas por nombre. **Solo super admin.**

    Está paginado: `total` es la cantidad total que cumple el filtro y
    `limit`/`offset` controlan la página. `q` filtra por texto dentro del nombre
    (sin distinguir mayúsculas).
    """
    items, total = await list_sections(db, q=q, limit=limit, offset=offset)
    return SectionList(
        items=[to_public(s) for s in items], total=total, limit=limit, offset=offset
    )


@sections_router.get(
    "/{id_section}",
    response_model=SectionPublic,
    summary="Consultar una comisión",
    responses={**_AUTH_ERRORS, **_NOT_FOUND},
)
async def get_section_route(
    id_section: int, db: db_dependency, _: super_admin_dependency
):
    """Devuelve una comisión por su id. **Solo super admin.**"""
    return to_public(await get_section(db, id_section))


@sections_router.patch(
    "/{id_section}",
    response_model=SectionPublic,
    summary="Modificar una comisión",
    responses={
        **_AUTH_ERRORS,
        **_NOT_FOUND,
        409: {"description": "Ya existe otra comisión con ese nombre"},
        422: {"description": "Nombre inválido, ausente o campos desconocidos"},
    },
)
async def update_section_route(
    id_section: int,
    data: SectionUpdate,
    db: db_dependency,
    _: super_admin_dependency,
):
    """
    Cambia el nombre de una comisión. **Solo super admin.**

    Aplican las mismas reglas que al crearla: se normaliza a mayúsculas y no
    puede coincidir con el nombre de otra comisión. Reenviar el mismo nombre no
    da error.
    """
    return to_public(await update_section(db, id_section, data))


@sections_router.delete(
    "/{id_section}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una comisión",
    responses={
        **_AUTH_ERRORS,
        **_NOT_FOUND,
        409: {"description": "La comisión está en uso (tiene datos asociados) y no se puede eliminar"},
    },
)
async def delete_section_route(
    id_section: int, db: db_dependency, _: super_admin_dependency
):
    """
    Elimina una comisión. **Solo super admin.** La acción es irreversible; el
    nombre queda libre para volver a usarse.

    Cuando existan alumnos u otros datos asociados a la comisión, responderá 409
    en vez de borrarla.
    """
    await delete_section(db, id_section)