from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from config.database import db_dependency
from schemas.status import MembershipStatus
from schemas.student_project import (
    StudentProjectList,
    StudentProjectPublic,
    StudentProjectUpdate,
)
from utils.auth import user_dependency
from utils.permissions import student_dependency
from utils.projects import build_access, get_project
from utils.student_projects import (
    decide_membership,
    join_project,
    list_members,
)

student_projects_router = APIRouter(tags=["members"])

_AUTH_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}


@student_projects_router.post(
    "/projects/{id_project}/members",
    response_model=StudentProjectPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Unirse a un proyecto (grupo)",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El usuario no es alumno"},
        404: {"description": "No existe el proyecto"},
        409: {
            "description": (
                "El proyecto no está `uninsured` (Desasegurado), ya hay una solicitud "
                "propia, o el alumno ya pertenece (`member`) a otro proyecto"
            )
        },
    },
)
async def join_project_route(
    id_project: int,
    response: Response,
    db: db_dependency,
    student: student_dependency,
):
    """
    El **alumno logueado** se une a un grupo. **Solo alumnos** (no profesores ni
    super admin).

    - Solo se puede pedir entrar mientras el proyecto está **`uninsured`**
      (Desasegurado); en cualquier otro estado responde **409**.
    - Si el grupo todavía **no tiene jefe**, el alumno entra como jefe y queda
      `active`; si ya tiene, queda `pending_approval` a la espera de que el jefe
      lo acepte o rechace.
    - Un alumno solo puede ser **`member`** (`active`/`finished`) de **un** grupo
      en todo el sistema. Si ya pertenece a otro y este grupo está vacío (sería
      jefe/`active`), responde **409**. Si se une como `member`, sus otras
      solicitudes `pending_approval` pasan a `rejected`.
    - Una solicitud `rejected` se puede **volver a enviar** (responde `200`); en
      cualquier otro estado previo responde **409**.
    """
    membership, created = await join_project(db, student.id_student, id_project)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return membership


@student_projects_router.get(
    "/projects/{id_project}/members",
    response_model=StudentProjectList,
    summary="Listar los integrantes de un proyecto",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El usuario no tiene privilegios sobre el proyecto"},
        404: {"description": "No existe el proyecto"},
        422: {"description": "Algún `status` no es un estado de membresía válido"},
    },
)
async def get_project_members_route(
    id_project: int,
    db: db_dependency,
    user: user_dependency,
    status_filter: Annotated[
        list[MembershipStatus] | None,
        Query(alias="status", description="Estados de la membresía a incluir (repetible)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los integrantes de un grupo. **Privilegiados**: el jefe, los miembros
    del grupo con membresía `active`/`finished`, los profesores del curso lectivo
    y los super admin.

    Cada integrante incluye `is_leader` y su `status` de membresía, más los datos
    públicos del alumno (nombre, apellido y legajo; **nunca** el mail ni datos
    privados). Filtrable por `status` (repetible). Orden: el jefe primero, luego
    por estado (`active`, `pending_approval`, `finished`, `abandoned`, `expelled`,
    `rejected`) y por id de membresía. Está paginado.
    """
    access = await build_access(db, user)
    project = await get_project(db, id_project)
    if not access.is_privileged(project):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a member, a professor of this section year or a super admin can see the members",
        )
    items, total = await list_members(
        db,
        id_project,
        statuses=status_filter or [],
        limit=limit,
        offset=offset,
    )
    return StudentProjectList(items=items, total=total, limit=limit, offset=offset)


@student_projects_router.patch(
    "/projects/{id_project}/members/{id_student_project}",
    response_model=StudentProjectPublic,
    summary="Aceptar o rechazar una solicitud de ingreso",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El usuario no es el jefe del grupo"},
        404: {"description": "No existe el proyecto o la membresía"},
        409: {
            "description": (
                "La transición no es válida (por ejemplo, ya no está "
                "`pending_approval`), o el alumno ya pertenece a otro proyecto"
            )
        },
        422: {"description": "`status` faltante, distinto de `active`/`rejected` o campos desconocidos"},
    },
)
async def decide_membership_route(
    id_project: int,
    id_student_project: int,
    data: StudentProjectUpdate,
    db: db_dependency,
    user: user_dependency,
):
    """
    **El jefe del grupo** acepta (`active`) o rechaza (`rejected`) una solicitud
    de ingreso. Nadie más puede hacerlo.

    Solo se puede decidir sobre una membresía `pending_approval`. Al aceptar, el
    alumno no puede ya pertenecer (`member`) a otro proyecto (409) y sus otras
    solicitudes `pending_approval` pasan a `rejected`.
    """
    return await decide_membership(
        db, user.id_user, id_project, id_student_project, data.status
    )
