from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from config.database import db_dependency
from schemas.project import (
    Privacy,
    ProjectBulkCreate,
    ProjectCreate,
    ProjectList,
    ProjectOverviewPublic,
    ProjectPublic,
    ProjectUpdate,
)
from schemas.project_status import ProjectStatusList
from schemas.status import MembershipStatus
from utils.auth import user_dependency
from utils.permissions import professor_dependency
from utils.project_statuses import list_project_status_history, to_public as status_history_public
from utils.projects import (
    advance_project,
    approve_project,
    build_access,
    cancel_project,
    create_project,
    create_projects_bulk,
    delete_project,
    get_project,
    insure_project,
    list_projects,
    reject_project,
    retry_project,
    submit_project,
    to_public,
    uninsure_project,
    update_project,
)
from models.state import MEMBER_CODES
from utils.student_projects import build_overview

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
    - Se crea con privacidad `public`, en estado `uninsured` (Desasegurado) y
      sin nombre, descripción, objetivo ni problemática (todos `null`); se
      completan después. Mientras esté `uninsured` el proyecto se trata siempre
      como público, sin importar su privacidad.
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
    14). Mismos permisos que `POST /projects`. Es todo o nada. Cada grupo nace
    con privacidad `public` y en estado `uninsured` (Desasegurado).
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
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Busca dentro del nombre del proyecto",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los proyectos. **Cualquier usuario logueado.**

    La visibilidad depende de la privacidad:

    - `uninsured` (Desasegurado): se trata siempre como público, cualquiera ve
      todo el detalle (aunque la privacidad almacenada sea `private`/`protected`).
    - `public`: cualquier usuario ve todo el detalle.
    - `protected`: los privilegiados (miembros del grupo, profesores del curso
      lectivo y super admin) ven todo; el resto ve solo la información básica
      (`restricted` es `true` y el detalle viene en `null`).
    - `private`: solo los privilegiados; para el resto **no aparece** en el
      listado ni se cuenta en `total`.

    El filtro `privacy` usa la privacidad efectiva (un `uninsured` cuenta como
    `public`). El filtro `q` busca texto dentro del nombre del proyecto (sin
    distinguir mayúsculas).

    Orden: año más reciente, comisión y número de grupo. Está paginado: `total`
    es la cantidad que cumple los filtros y es visible para el usuario.
    """
    access = await build_access(db, user)
    items, total = await list_projects(
        db,
        access,
        id_section_year=id_section_year,
        year=year,
        id_section=id_section,
        privacy=privacy,
        q=q,
        limit=limit,
        offset=offset,
    )
    return ProjectList(
        items=[to_public(p, restricted=not access.can_see_detail(p)) for p in items],
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
        403: {"description": "El proyecto es privado y el usuario no tiene privilegios"},
        404: {"description": "No existe el proyecto"},
    },
)
async def get_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    Devuelve el detalle de un proyecto. **Cualquier usuario logueado**, según la
    privacidad:

    - `uninsured` (Desasegurado): se trata siempre como público.
    - `public`: cualquier usuario, con todo el detalle.
    - `protected`: los privilegiados (miembros, profesores del curso lectivo y
      super admin) ven todo; el resto recibe `200` con `restricted` en `true` y
      los campos de detalle en `null`.
    - `private`: solo los privilegiados; el resto recibe **403**.
    """
    access = await build_access(db, user)
    project = await get_project(db, id_project)
    if not access.can_see_project(project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This project is private")
    return to_public(project, restricted=not access.can_see_detail(project))


@projects_router.get(
    "/{id_project}/overview",
    response_model=ProjectOverviewPublic,
    summary="Consultar un proyecto con sus integrantes y responsables",
    responses={
        **_READ_ERRORS,
        403: {
            "description": (
                "El proyecto es privado y el usuario no tiene privilegios, o un "
                "usuario no privilegiado intentó filtrar integrantes por `status`"
            )
        },
        404: {"description": "No existe el proyecto"},
        422: {"description": "Algún `status` no es un estado de membresía válido"},
    },
)
async def get_project_overview_route(
    id_project: int,
    db: db_dependency,
    user: user_dependency,
    status_filter: Annotated[
        list[MembershipStatus] | None,
        Query(
            alias="status",
            description="Estados de membresía a incluir (repetible; solo privilegiados)",
        ),
    ] = None,
):
    """
    Devuelve un proyecto junto con sus **integrantes**, sus **responsables** (los
    profesores asignados a su curso lectivo) y su **jefe**. **Cualquier usuario
    logueado**, según la privacidad efectiva:

    - `uninsured` (Desasegurado) y `public`: cualquier usuario ve el detalle
      completo, los integrantes, los responsables y el jefe.
    - `protected`: los privilegiados (miembros del grupo con membresía `member`,
      profesores del curso lectivo y super admin) ven todo; el resto ve la
      información básica (`restricted` en `true`) y también los integrantes, los
      responsables y el jefe.
    - `private`: solo los privilegiados; el resto recibe **403**.

    Los integrantes son, por defecto, los `active` y `finished` (la categoría
    `member`). El parámetro repetible `status` (solo privilegiados) permite pedir
    otros estados (`pending_approval`, `abandoned`, `expelled`, `rejected`); un
    no privilegiado que lo envíe recibe **403**, y un estado inválido **422**.

    Cada integrante expone los datos públicos del alumno (nombre, apellido,
    legajo), su antigüedad (`enrolled_at`) y su estado; **nunca** el mail. El
    `responsible` es la lista de profesores del curso lectivo (sin mail), y el
    `leader` es el jefe del grupo (`is_leader`), o `null` si no tiene.
    """
    access = await build_access(db, user)
    project = await get_project(db, id_project)
    if not access.can_see_project(project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This project is private")
    if status_filter and not access.is_privileged(project):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only privileged users can filter members by status",
        )

    statuses = status_filter or list(MEMBER_CODES)
    return await build_overview(
        db,
        project,
        restricted=not access.can_see_detail(project),
        statuses=statuses,
    )


@projects_router.get(
    "/{id_project}/status-history",
    response_model=ProjectStatusList,
    summary="Historial de estados de un proyecto",
    responses={
        **_READ_ERRORS,
        403: {"description": "El proyecto es privado y el usuario no tiene privilegios"},
        404: {"description": "No existe el proyecto"},
    },
)
async def get_project_status_history_route(
    id_project: int,
    db: db_dependency,
    user: user_dependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Devuelve el historial de estados de un proyecto, en orden cronológico (el
    registro más viejo primero). **Cualquier usuario logueado**, con la misma
    visibilidad que `GET /projects/{id}`:

    - `uninsured` (Desasegurado), `public` y `protected`: cualquier usuario.
    - `private`: solo los privilegiados (miembros, profesores del curso lectivo
      y super admin); el resto recibe **403**.

    Cada registro indica el estado anterior (`status_from`, `null` en la
    creación), el estado nuevo (`status_to`) y cuándo ocurrió (`changed_at`).
    """
    access = await build_access(db, user)
    project = await get_project(db, id_project)
    if not access.can_see_project(project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This project is private")
    items, total = await list_project_status_history(
        db, id_project, limit=limit, offset=offset
    )
    return ProjectStatusList(
        items=[status_history_public(ps) for ps in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@projects_router.patch(
    "/{id_project}",
    response_model=ProjectPublic,
    summary="Modificar un proyecto",
    responses={
        **_READ_ERRORS,
        403: {
            "description": (
                "El usuario no es profesor del curso lectivo, super admin ni "
                "miembro del grupo (`active`/`finished`)"
            )
        },
        404: {"description": "No existe el proyecto"},
        409: {"description": "El proyecto está en un estado final (`approved`/`cancelled`)"},
        422: {
            "description": (
                "Body vacío, `privacy` nula o inválida, `name` en blanco o campos "
                "desconocidos"
            )
        },
    },
)
async def update_project_route(
    id_project: int,
    data: ProjectUpdate,
    db: db_dependency,
    user: user_dependency,
):
    """
    Modifica los atributos de un proyecto. **Privilegiados**: profesores del
    curso lectivo, super admin y miembros del grupo con membresía `active` o
    `finished`.

    **Campos editables** (opcionales, se envían solo los que cambian): `name`,
    `description`, `objective`, `problem` y `privacy`. Enviar un campo de texto
    con `null` lo **limpia**; `privacy` es obligatoria y no admite `null`.

    No se puede modificar si el proyecto está en un estado final (`approved` o
    `cancelled`): responde **409**. El `group_number` y el curso lectivo no se
    pueden cambiar.
    """
    return await update_project(db, await build_access(db, user), id_project, data)


@projects_router.post(
    "/{id_project}/insure",
    response_model=ProjectPublic,
    summary="Asegurar un proyecto (grupo)",
    responses={
        **_READ_ERRORS,
        403: {
            "description": (
                "El usuario no es el jefe del grupo, ni profesor del curso lectivo, "
                "ni super admin"
            )
        },
        404: {"description": "No existe el proyecto"},
        409: {
            "description": (
                "El proyecto no está `uninsured` (ya se aseguró o está en un estado "
                "final), o la cantidad de integrantes `active` está fuera del rango "
                "`min_students`-`max_students` del curso lectivo"
            )
        },
    },
)
async def insure_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    Asegura un grupo: lo saca de `uninsured` (Desasegurado) y lo pasa a un estado
    asegurado, dejando el equipo confirmado. Lo puede hacer **el jefe del grupo**,
    **un profesor de ese curso lectivo** o **un super admin**.

    - Solo se puede desde `uninsured`: si el proyecto ya está asegurado (`in_idea`,
      `in_progress`, `pending_approval` o `rejected`) o final (`approved` o
      `cancelled`), responde **409**.
    - La cantidad de integrantes `active` debe estar entre `min_students` y
      `max_students` del curso lectivo; si no, responde **409**.
    - El estado destino es el subestado asegurado recordado (la última vez que
      estuvo asegurado) o, si el grupo nunca lo estuvo, `in_idea`.
    - Al asegurar, todas las solicitudes `pending_approval` del grupo pasan a
      `rejected`, y el proyecto pasa a aplicar su privacidad guardada (deja de
      tratarse como público). A partir de acá **no se pueden unir** integrantes
      nuevos.
    """
    return await insure_project(db, await build_access(db, user), user.id_user, id_project)


@projects_router.delete(
    "/{id_project}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un proyecto",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe el proyecto"},
        409: {
            "description": (
                "El proyecto tiene alumnos, o no está en estado `uninsured` "
                "(Desasegurado)"
            )
        },
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

    Solo se puede si el proyecto está **completamente vacío** (sin alumnos) y
    en estado **`uninsured`** (Desasegurado); si no, responde 409. Una vez
    asegurado (`in_idea`, `in_progress`, `pending_approval` o `rejected`) o
    final (`approved` o `cancelled`) ya no se puede eliminar.

    El número de grupo eliminado no se reutiliza automáticamente, pero puede
    volver a crearse enviándolo en `group_number`.
    """
    await delete_project(db, await build_access(db, user), id_project)


_TRANSITION_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {
        "description": (
            "El usuario no es profesor, o no está asignado a ese curso lectivo "
            "(los super admin pueden en cualquiera)"
        )
    },
    404: {"description": "No existe el proyecto"},
    409: {"description": "El proyecto no está en un estado que permita esta transición"},
}


@projects_router.post(
    "/{id_project}/uninsure",
    response_model=ProjectPublic,
    summary="Desasegurar un proyecto (grupo)",
    responses=_TRANSITION_ERRORS,
)
async def uninsure_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    **Desasegura** un grupo: lo pasa de un estado asegurado a `uninsured`
    (Desasegurado). **Solo profesores de ese curso lectivo y super admin.**

    - Solo desde un estado asegurado (`in_idea`, `in_progress`, `pending_approval`
      o `rejected`); si el proyecto ya está `uninsured` o en un estado final
      (`approved`/`cancelled`), responde **409**.
    - Guarda la memoria del subestado: al volver a asegurar (`POST /projects/{id}/insure`)
      se retoma el mismo subestado desde el que se desaseguró.
    - Al estar `uninsured`, el proyecto se trata siempre como público y **se pueden
      unir integrantes nuevos**.
    """
    return await uninsure_project(db, await build_access(db, user), id_project)


@projects_router.post(
    "/{id_project}/start",
    response_model=ProjectPublic,
    summary="Pasar el proyecto de En idea a En proceso",
    responses=_TRANSITION_ERRORS,
)
async def advance_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    Pasa el proyecto de **`in_idea`** (En idea) a **`in_progress`** (En proceso).
    **Solo profesores de ese curso lectivo y super admin.**

    Responde **409** si el proyecto no está en `in_idea`.
    """
    return await advance_project(db, await build_access(db, user), id_project)


@projects_router.post(
    "/{id_project}/submit",
    response_model=ProjectPublic,
    summary="Enviar el proyecto a aprobación",
    responses=_TRANSITION_ERRORS,
)
async def submit_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    Pasa el proyecto de **`in_progress`** (En proceso) a **`pending_approval`**
    (Pendiente de aprobación). **Solo profesores de ese curso lectivo y super admin.**

    Responde **409** si el proyecto no está en `in_progress`.
    """
    return await submit_project(db, await build_access(db, user), id_project)


@projects_router.post(
    "/{id_project}/approve",
    response_model=ProjectPublic,
    summary="Aprobar un proyecto",
    responses=_TRANSITION_ERRORS,
)
async def approve_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    **Aprueba** un proyecto: pasa de **`pending_approval`** a **`approved`**
    (estado final). **Solo profesores de ese curso lectivo y super admin.**

    Al aprobar, todas las membresías `active` pasan a `finished` (finalizadas) y
    las solicitudes `pending_approval` pendientes pasan a `rejected`.

    Responde **409** si el proyecto no está en `pending_approval`.
    """
    return await approve_project(db, await build_access(db, user), id_project)


@projects_router.post(
    "/{id_project}/reject",
    response_model=ProjectPublic,
    summary="Rechazar un proyecto",
    responses=_TRANSITION_ERRORS,
)
async def reject_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    **Rechaza** un proyecto: pasa de **`pending_approval`** a **`rejected`**
    (rechazado). **Solo profesores de ese curso lectivo y super admin.**

    Responde **409** si el proyecto no está en `pending_approval`.
    """
    return await reject_project(db, await build_access(db, user), id_project)


@projects_router.post(
    "/{id_project}/retry",
    response_model=ProjectPublic,
    summary="Reintentar un proyecto rechazado",
    responses=_TRANSITION_ERRORS,
)
async def retry_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    Pasa el proyecto de **`rejected`** (Rechazado) a **`in_progress`** (En proceso)
    para que el grupo corrija y vuelva a enviarlo. **Solo profesores de ese curso
    lectivo y super admin.**

    Responde **409** si el proyecto no está en `rejected`.
    """
    return await retry_project(db, await build_access(db, user), id_project)


@projects_router.post(
    "/{id_project}/cancel",
    response_model=ProjectPublic,
    summary="Cancelar un proyecto",
    responses=_TRANSITION_ERRORS,
)
async def cancel_project_route(id_project: int, db: db_dependency, user: user_dependency):
    """
    **Cancela** un proyecto: lo pasa a **`cancelled`** (Cancelado), un estado
    final. **Solo profesores de ese curso lectivo y super admin.**

    Se puede cancelar desde cualquier estado **no final** (`uninsured`, `in_idea`,
    `in_progress`, `pending_approval` o `rejected`). Responde **409** si el
    proyecto ya está `approved` o `cancelled`.

    Al cancelar, todas las membresías `active` pasan a `abandoned` (abandono) y
    las solicitudes `pending_approval` pasan a `rejected`.
    """
    return await cancel_project(db, await build_access(db, user), id_project)