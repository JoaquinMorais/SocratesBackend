from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from config.database import db_dependency
from schemas.delivery import (
    DeliveryList,
    DeliveryPublic,
    DeliveryRepairCreate,
    DeliveryUpdate,
)
from utils.auth import user_dependency
from utils.deliveries import (
    approve_delivery,
    create_delivery,
    get_delivery,
    list_activity_deliveries,
    list_project_deliveries,
    reject_delivery,
    submit_delivery,
    to_public,
    update_delivery,
    withdraw_delivery,
)
from utils.projects import build_access

deliveries_router = APIRouter(tags=["deliveries"])

_AUTH_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}
_PROJECT_READ_ERRORS = {
    **_AUTH_ERRORS,
    403: {"description": "El usuario no es miembro del proyecto ni staff del curso"},
    404: {"description": "No existe el proyecto"},
}
_DELIVERY_ERRORS = {
    **_AUTH_ERRORS,
    403: {"description": "El usuario no es miembro del proyecto ni staff del curso"},
    404: {"description": "No existe la entrega"},
}


@deliveries_router.get(
    "/projects/{id_project}/deliveries",
    response_model=DeliveryList,
    summary="Listar las entregas de un proyecto",
    responses=_PROJECT_READ_ERRORS,
)
async def get_project_deliveries(
    id_project: int,
    db: db_dependency,
    user: user_dependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista **todas las entregas del proyecto**, incluidas las filas pre-creadas
    todavía vacías. **Integrantes `active`/`finished`, profesor del curso o
    super admin.**

    Cada entrega incluye los datos de la actividad y del proyecto, el link, las
    dos notas y las fechas de envío y última modificación. Orden: fecha de
    entrega de la actividad y luego id. Está paginado.
    """
    access = await build_access(db, user)
    return await list_project_deliveries(
        db, access, id_project, limit=limit, offset=offset
    )


@deliveries_router.get(
    "/deliveries/{id_delivery}",
    response_model=DeliveryPublic,
    summary="Consultar una entrega",
    responses=_DELIVERY_ERRORS,
)
async def get_delivery_route(
    id_delivery: int, db: db_dependency, user: user_dependency
):
    """
    Devuelve una entrega con su actividad y proyecto. **Integrantes
    `active`/`finished`, profesor del curso o super admin.**
    """
    access = await build_access(db, user)
    delivery = await get_delivery(db, id_delivery)
    if not access.can_manage(
        delivery.project.id_section_year
    ) and delivery.project.id_project not in access.project_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot see this delivery")
    return to_public(delivery)


@deliveries_router.patch(
    "/deliveries/{id_delivery}",
    response_model=DeliveryPublic,
    summary="Enviar o modificar una entrega",
    responses={
        **_DELIVERY_ERRORS,
        409: {
            "description": (
                "Un alumno intenta modificar una entrega de un proyecto final"
            )
        },
        422: {"description": "Body vacío, notas fuera de 1-100, link inválido o campos desconocidos"},
    },
)
async def update_delivery_route(
    id_delivery: int,
    data: DeliveryUpdate,
    db: db_dependency,
    user: user_dependency,
):
    """
    Actualiza el link y/o las notas de una entrega. **Integrantes
    `active`/`finished` del proyecto o staff del curso.**

    - El alumno solo puede enviar/corregir `link`, y solo mientras el proyecto no
      sea final (`approved`/`cancelled`). Si envía notas, responde **403**.
    - El profesor del curso o super admin puede modificar `link`,
      `activity_grade` y `development_grade`, incluso con el proyecto final.
    - Las notas van de 1 a 100. El link debe ser una URL `http` o `https`.
    - Se actualiza `updated_at`; el primer link no nulo setea `submitted_at`.
    - Body vacío: **422**; entrega inexistente: **404**.
    """
    access = await build_access(db, user)
    return await update_delivery(db, access, id_delivery, data)


async def _delivery_action(
    db, user, id_delivery: int, action
):
    access = await build_access(db, user)
    return await action(db, access, id_delivery)


@deliveries_router.post(
    "/deliveries/{id_delivery}/submit",
    response_model=DeliveryPublic,
    summary="Entregar una entrega de proyecto",
    responses={
        **_DELIVERY_ERRORS,
        409: {
            "description": (
                "La entrega no está en `requested`/`pending_modification`, o la "
                "actividad requiere link y no hay uno cargado"
            )
        },
    },
)
async def submit_delivery_route(
    id_delivery: int, db: db_dependency, user: user_dependency
):
    """
    El grupo marca la entrega como terminada. **Integrantes `active`/`finished`
    o staff del curso.**

    - Solo desde `requested` o `pending_modification`; pasa a
      `pending_approval`.
    - Si `Activity.link_required` es `true`, debe existir un link (**409**).
    - Mientras está `pending_approval`, los integrantes no pueden modificar la
      entrega: deben usar `/withdraw` para volver a `requested`.
    """
    return await _delivery_action(db, user, id_delivery, submit_delivery)


@deliveries_router.post(
    "/deliveries/{id_delivery}/withdraw",
    response_model=DeliveryPublic,
    summary="Retirar una entrega para modificarla",
    responses={
        **_DELIVERY_ERRORS,
        409: {"description": "La entrega no está `pending_approval`"},
    },
)
async def withdraw_delivery_route(
    id_delivery: int, db: db_dependency, user: user_dependency
):
    """
    Vuelve una entrega de `pending_approval` a `requested` para que el grupo
    pueda seguir modificándola. **Integrantes `active`/`finished` o staff.**
    """
    return await _delivery_action(db, user, id_delivery, withdraw_delivery)


@deliveries_router.post(
    "/deliveries/{id_delivery}/approve",
    response_model=DeliveryPublic,
    summary="Aprobar una entrega",
    responses={
        **_DELIVERY_ERRORS,
        409: {"description": "La entrega no está `pending_approval`"},
    },
)
async def approve_delivery_route(
    id_delivery: int, db: db_dependency, user: user_dependency
):
    """
    Aprueba una entrega en `pending_approval`. **Solo profesor del curso o
    super admin.** Pasa a `approved` (final).
    """
    return await _delivery_action(db, user, id_delivery, approve_delivery)


@deliveries_router.post(
    "/deliveries/{id_delivery}/reject",
    response_model=DeliveryPublic,
    summary="Rechazar una entrega",
    responses={
        **_DELIVERY_ERRORS,
        409: {"description": "La entrega no está `pending_approval`"},
    },
)
async def reject_delivery_route(
    id_delivery: int, db: db_dependency, user: user_dependency
):
    """
    Rechaza una entrega en `pending_approval`. **Solo profesor del curso o
    super admin.** Pasa a `pending_modification`; los comentarios se agregarán
    más adelante.
    """
    return await _delivery_action(db, user, id_delivery, reject_delivery)


@deliveries_router.post(
    "/projects/{id_project}/deliveries",
    response_model=DeliveryPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Reparar una entrega faltante",
    responses={
        **_PROJECT_READ_ERRORS,
        409: {"description": "El proyecto ya tiene una entrega para esa actividad"},
        404: {"description": "No existe el proyecto o la actividad"},
        422: {"description": "Actividad de otro curso, sin datos o campos desconocidos"},
    },
)
async def create_delivery_route(
    id_project: int,
    data: DeliveryRepairCreate,
    db: db_dependency,
    user: user_dependency,
):
    """
    Crea una entrega faltante para un proyecto y una actividad. **Uso de
    reparación/backfill**: lo normal es que las entregas ya estén pre-creadas.

    - El alumno puede crear únicamente con `link` y con proyecto no final.
    - El profesor del curso o super admin puede crear con link y/o notas.
    - La actividad debe pertenecer al mismo curso lectivo que el proyecto.
    - Si la fila ya existe responde **409**.
    """
    access = await build_access(db, user)
    return await create_delivery(db, access, id_project, data)


@deliveries_router.get(
    "/activities/{id_activity}/deliveries",
    response_model=DeliveryList,
    summary="Listar las entregas de una actividad",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El usuario no es profesor del curso ni super admin"},
        404: {"description": "No existe la actividad"},
    },
)
async def get_activity_deliveries(
    id_activity: int,
    db: db_dependency,
    user: user_dependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista las entregas de **todos los proyectos** para una actividad, incluidas
    las vacías pre-creadas. **Solo profesor del curso o super admin.** Orden:
    número de grupo.
    """
    access = await build_access(db, user)
    return await list_activity_deliveries(
        db, access, id_activity, limit=limit, offset=offset
    )
