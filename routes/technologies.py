from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.technology import (
    TechnologyCreate,
    TechnologyList,
    TechnologyPublic,
    TechnologyUpdate,
)
from utils.auth import user_dependency
from utils.permissions import professor_dependency
from utils.technologies import (
    create_technology,
    delete_technology,
    get_technology,
    list_technologies,
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


@technologies_router.post(
    "",
    response_model=TechnologyPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una tecnología",
    responses={
        **_WRITE_ERRORS,
        409: {"description": "Ya existe una tecnología con ese nombre"},
        422: {"description": "Datos inválidos, campos faltantes o desconocidos"},
    },
)
async def create_technology_route(
    data: TechnologyCreate, db: db_dependency, _: professor_dependency
):
    """
    Crea una tecnología. **Profesores y super admin.**

    - El nombre se guarda sin espacios sobrantes y es obligatorio (máximo 100
      caracteres); no puede repetirse sin distinguir mayúsculas: `React` y
      `react` son la misma tecnología.
    - `description` es opcional (máximo 500 caracteres).
    """
    return to_public(await create_technology(db, data))


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
    responses={
        **_WRITE_ERRORS,
        **_NOT_FOUND,
        409: {"description": "Ya existe otra tecnología con ese nombre"},
        422: {"description": "Body vacío, datos inválidos o campos desconocidos"},
    },
)
async def update_technology_route(
    id_technology: int, data: TechnologyUpdate, db: db_dependency, _: professor_dependency
):
    """
    Modifica una tecnología. **Profesores y super admin.** Se envían solo los
    campos que cambian.

    - `name` no admite `null`; cambiar el casing (por ejemplo `react` a `React`)
      está permitido porque la unicidad no distingue mayúsculas.
    - `description: null` limpia el campo.
    """
    return to_public(await update_technology(db, id_technology, data))


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
    quitarla de esos proyectos.
    """
    await delete_technology(db, id_technology)
