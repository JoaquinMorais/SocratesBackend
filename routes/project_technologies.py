from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.technology import (
    ProjectTechnologyBulkCreate,
    ProjectTechnologyCreate,
    TechnologyList,
    TechnologyPublic,
)
from utils.auth import user_dependency
from utils.projects import build_access
from utils.project_technologies import (
    add_technologies_bulk,
    add_technology,
    list_project_technologies,
    remove_technology,
)
from utils.technologies import to_public

project_technologies_router = APIRouter(tags=["project-technologies"])

_MANAGE_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {
        "description": (
            "El usuario no es privilegiado del proyecto (miembro `active`/`finished`, "
            "profesor del curso lectivo o super admin)"
        )
    },
    409: {"description": "El proyecto está en un estado final"},
}


@project_technologies_router.post(
    "/projects/{id_project}/technologies",
    response_model=TechnologyPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Asociar una tecnología a un proyecto",
    responses={
        **_MANAGE_ERRORS,
        404: {"description": "No existe el proyecto o la tecnología"},
        422: {"description": "Datos inválidos, campos faltantes o desconocidos"},
    },
)
async def add_technology_route(
    id_project: int, data: ProjectTechnologyCreate, db: db_dependency, user: user_dependency
):
    """
    Asocia una tecnología al proyecto. **Privilegiados del proyecto** (miembros
    `active`/`finished`, profesor del curso lectivo o super admin), solo
    mientras el proyecto **no esté en un estado final**.

    Una tecnología puede asociarse una sola vez a cada proyecto (409 si ya lo
    está); la consulta de tecnologías del proyecto usa este id.
    """
    access = await build_access(db, user)
    technology = await add_technology(db, access, id_project, data.id_technology)
    return to_public(technology)


@project_technologies_router.post(
    "/projects/{id_project}/technologies/bulk",
    response_model=list[TechnologyPublic],
    status_code=status.HTTP_201_CREATED,
    summary="Asociar tecnologías en lote",
    responses={
        **_MANAGE_ERRORS,
        404: {"description": "No existe el proyecto"},
        409: {"description": "El proyecto cambió mientras se creaba el lote"},
        422: {
            "description": (
                "Lista vacía o de más de 100, campos desconocidos, o alguna fila "
                "inválida (detalle por fila: id duplicado, tecnología inexistente "
                "o ya asociada)"
            )
        },
    },
)
async def add_technologies_bulk_route(
    id_project: int, data: ProjectTechnologyBulkCreate, db: db_dependency, user: user_dependency
):
    """
    Asocia varias tecnologías al proyecto en una sola llamada.
    **Privilegiados del proyecto**, solo mientras el proyecto **no esté en un
    estado final**.

    Todo o nada: si alguna fila falla (id repetido en la lista, tecnología
    inexistente o ya asociada), responde **422** con el detalle de cada fila y
    no se vincula ninguna. Devuelve las tecnologías asociadas, ordenadas por
    nombre.
    """
    access = await build_access(db, user)
    technologies = await add_technologies_bulk(db, access, id_project, data.id_technologies)
    return [to_public(t) for t in technologies]


@project_technologies_router.get(
    "/projects/{id_project}/technologies",
    response_model=TechnologyList,
    summary="Listar las tecnologías de un proyecto",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El proyecto es privado y el usuario no tiene privilegios"},
        404: {"description": "No existe el proyecto"},
    },
)
async def get_project_technologies(
    id_project: int,
    db: db_dependency,
    user: user_dependency,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Busca dentro del nombre"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista las tecnologías asociadas a un proyecto. **Cualquier usuario
    logueado**, con la misma visibilidad que el proyecto: en `private` solo los
    privilegiados (en otro caso **403**); `protected` y `public` (y todo
    proyecto `uninsured`, Desasegurado) se ven.

    Ordenadas por nombre y paginadas (`total` es la cantidad que cumple el
    filtro).
    """
    access = await build_access(db, user)
    items, total = await list_project_technologies(
        db, access, id_project, q=q, limit=limit, offset=offset
    )
    return TechnologyList(
        items=[to_public(t) for t in items], total=total, limit=limit, offset=offset
    )


@project_technologies_router.delete(
    "/projects/{id_project}/technologies/{id_technology}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar una tecnología de un proyecto",
    responses={
        **_MANAGE_ERRORS,
        404: {"description": "No existe el proyecto, o la tecnología no está asociada"},
    },
)
async def remove_technology_route(
    id_project: int, id_technology: int, db: db_dependency, user: user_dependency
):
    """
    Quita una tecnología del proyecto. **Privilegiados del proyecto**, solo
    mientras el proyecto **no esté en un estado final**.

    Solo se borra el vínculo: la tecnología sigue existiendo.
    """
    access = await build_access(db, user)
    await remove_technology(db, access, id_project, id_technology)
