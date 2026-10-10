from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from config.database import db_dependency
from schemas.project import (
    Privacy,
    ProjectBulkCreate,
    ProjectCreate,
    ProjectList,
    ProjectPublic,
)
from utils.auth import user_dependency
from utils.permissions import professor_dependency
from utils.projects import (
    build_access,
    create_project,
    create_projects_bulk,
    delete_project,
    get_project,
    list_projects,
    to_public,
)

projects_router = APIRouter(prefix="/projects", tags=["projects"])

_READ_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}
_WRITE_ERRORS = {
    **_READ_ERRORS,
    403: {
        "description": (
            "El usuario no es profesor, o no está asignado a ese curso lectivo "
            "(los super admin pueden en cualquiera)"
        )
    },
}


@projects_router.post(
    "",
    response_model=ProjectPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un proyecto (grupo)",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe el curso lectivo"},
        409: {"description": "Ya existe ese número de grupo en el curso lectivo"},
        422: {"description": "Datos inválidos, campos faltantes o desconocidos"},
    },
)
async def create_project_route(
    data: ProjectCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Crea un grupo vacío en un curso lectivo. **Profesores asignados a ese curso
    lectivo** y **super admin** (en cualquiera).

    - `group_number` es opcional: si no se envía, toma el siguiente libre (el
      mayor existente + 1). No puede repetirse dentro del curso lectivo.
    - Se crea con privacidad `private` y sin nombre, descripción, objetivo ni
      problemática (todos `null`); se completan después.
    """
    return await create_project(db, await build_access(db, user), data)


@projects_router.post(
    "/bulk",
    response_model=list[ProjectPublic],
    status_code=status.HTTP_201_CREATED,
    summary="Crear varios proyectos (grupos) a la vez",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe el curso lectivo"},
        409: {"description": "Los números de grupo cambiaron mientras se creaban; reintentar"},
        422: {"description": "`quantity` fuera de 1-50, campos faltantes o desconocidos"},
    },
)
async def create_projects_bulk_route(
    data: ProjectBulkCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Crea de 1 a 50 grupos vacíos en un curso lectivo, con números consecutivos a
    partir del siguiente libre (si hay grupos 1 a 11, `quantity=3` crea 12, 13 y
    14). Mismos permisos que `POST /projects`. Es todo o nada.
    """
    return await create_projects_bulk(db, await build_access(db, user), data)


@projects_router.get(
    "",
    response_model=ProjectList,
    summary="Listar proyectos",
    responses=_READ_ERRORS,
)
async def get_projects(
    db: db_dependency,
    user: user_dependency,
    id_section_year: Annotated[int | None, Query(description="Filtrar por curso lectivo")] = None,
    year: Annotated[int | None, Query(description="Filtrar por año")] = None,
    id_section: Annotated[int | None, Query(description="Filtrar por comisión")] = None,
    privacy: Annotated[Privacy | None, Query(description="Filtrar por privacidad")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los proyectos. **Cualquier usuario logueado.**

    Los datos básicos (id, curso lectivo, número de grupo y privacidad) los ve
    cualquiera. El detalle (nombre, descripción, objetivo y problemática) depende
    de la privacidad:

    - `public` y `protected`: lo ve cualquier usuario.
    - `private`: solo los miembros del grupo, los profesores de ese curso lectivo
      y los super admin. Para el resto, `restricted` es `true` y esos campos
      vienen en `null`.

    Orden: año más reciente, comisión y número de grupo. Está paginado: `total`
    es la cantidad que cumple los filtros.
    """
    access = await build_access(db, user)
    items, total = await list_projects(
        db,
        id_section_year=id_section_year,
        year=year,
        id_section=id_section,
        privacy=privacy,
        limit=limit,
        offset=offset,
    )
    return ProjectList(
        items=[to_public(p, restricted=not access.can_see_info(p)) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@projects_router.get(
    "/{id_project}",
    response_model=ProjectPublic,
    summary="Consultar un proyecto",
    responses={
        **_READ_ERRORS,
        403: {"description": "El proyecto es privado y el usuario no tiene acceso"},
        404: {"description": "No existe el proyecto"},
    },
)
async def get_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    Devuelve el detalle de un proyecto. **Cualquier usuario logueado**, según la
    privacidad:

    - `public` y `protected`: cualquier usuario.
    - `private`: miembros del grupo, profesores de ese curso lectivo y super
      admin. El resto recibe 403 (los datos básicos siguen visibles en el listado).
    """
    access = await build_access(db, user)
    project = await get_project(db, id_project)
    if not access.can_see_info(project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This project is private")
    return to_public(project)


@projects_router.delete(
    "/{id_project}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un proyecto",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe el proyecto"},
        409: {"description": "El proyecto tiene alumnos y no se puede eliminar"},
    },
)
async def delete_project_route(
    id_project: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Elimina un proyecto. **Profesores de ese curso lectivo** y **super admin**.
    La acción es irreversible.

    Solo se puede si el proyecto está **completamente vacío** (sin alumnos); si
    no, responde 409. El número de grupo eliminado no se reutiliza
    automáticamente, pero puede volver a crearse enviándolo en `group_number`.
    """
    await delete_project(db, await build_access(db, user), id_project)