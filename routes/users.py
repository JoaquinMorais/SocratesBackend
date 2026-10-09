from typing import Annotated

from fastapi import APIRouter, Query

from config.database import db_dependency
from schemas.user import Role, UserList
from utils.permissions import super_admin_dependency
from utils.users import list_users, to_list_item

users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get(
    "",
    response_model=UserList,
    response_model_exclude_none=True,
    summary="Listar usuarios registrados",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es super admin"},
    },
)
async def get_users(
    db: db_dependency,
    _: super_admin_dependency,
    role: Annotated[Role | None, Query(description="Filtrar por rol")] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            description="Busca en nombre, apellido, legajo (exacto) y mail de profesores",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los usuarios registrados. **Solo super admin.**

    Devuelve solo datos públicos: nombre, legajo, mail, rol, y según el rol
    `enrollment_year` (alumnos) o `is_super_admin` (profesores). Nunca incluye
    contraseña ni fecha de nacimiento.

    Está paginado: `total` es la cantidad total que cumple los filtros y
    `limit`/`offset` controlan la página. Orden: apellido, nombre.
    """
    users, total = await list_users(db, role=role, q=q, limit=limit, offset=offset)
    return UserList(
        items=[to_list_item(u) for u in users], total=total, limit=limit, offset=offset
    )