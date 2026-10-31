from typing import Annotated

from fastapi import APIRouter, Query

from config.database import db_dependency
from schemas.status import Ambito, StatusList
from utils.auth import user_dependency
from utils.statuses import list_statuses, to_public

statuses_router = APIRouter(prefix="/statuses", tags=["statuses"])


@statuses_router.get(
    "",
    response_model=StatusList,
    summary="Listar estados",
    responses={401: {"description": "Token ausente, inválido o vencido"}},
)
async def get_statuses(
    db: db_dependency,
    _: user_dependency,
    ambito: Annotated[
        Ambito | None,
        Query(description="Filtrar por ámbito (project, student_project, student_section_year)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los estados disponibles. **Cualquier usuario logueado.**

    Cada estado pertenece a un `ambito` (`project`, `student_project` o `student_section_year`)
    y tiene un `code` (identificador), un `name` y una `description` para mostrar.
    `is_final` indica que es un estado terminal (no admite más transiciones) e
    `is_insured` que el estado de proyecto cuenta como "asegurado" (los cuatro
    estados internos: `in_idea`, `in_progress`, `pending_approval`, `rejected`).
    Sirve para que el frontend arme etiquetas y filtros.

    Por ahora los estados se cargan con el arranque del backend; todavía no hay
    endpoint para crearlos o modificarlos.
    """
    items, total = await list_statuses(db, ambito=ambito, limit=limit, offset=offset)
    return StatusList(
        items=[to_public(s) for s in items], total=total, limit=limit, offset=offset
    )
