from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.user import Role, UserList
from utils.permissions import super_admin_dependency
from utils.users import delete_user, list_users, to_list_item

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

    Devuelve datos públicos: nombre, legajo, mail, rol, fecha de nacimiento,
    edad, y según el rol `enrollment_year` (alumnos) o `is_super_admin`
    (profesores). Nunca incluye contraseña.

    Está paginado: `total` es la cantidad total que cumple los filtros y
    `limit`/`offset` controlan la página. Orden: apellido, nombre.
    """
    users, total = await list_users(db, role=role, q=q, limit=limit, offset=offset)
    return UserList(
        items=[to_list_item(u) for u in users], total=total, limit=limit, offset=offset
    )


@users_router.delete(
    "/{id_user}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un usuario (alta errónea)",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es super admin"},
        404: {"description": "No existe el usuario"},
        409: {
            "description": (
                "El usuario no se puede eliminar: un alumno con membresía "
                "`active`, `finished` o `pending_approval`; un profesor asignado "
                "a algún curso lectivo; o un super admin (hay que quitarle el rol "
                "antes con `PATCH /professors/{id}`)"
            )
        },
    },
)
async def delete_user_route(id_user: int, db: db_dependency, _: super_admin_dependency):
    """
    Elimina a un usuario. **Solo super admin.**

    Pensado solo para **altas erróneas**, no para dar de baja a alguien que ya
    participa del sistema. La regla depende del rol:

    - **Alumno**: no puede tener ninguna membresía `active`, `finished` ni
      `pending_approval` (**409**). Si solo tiene restos viejos (`abandoned`,
      `expelled`, `rejected`), se eliminan con él sin afectar a los proyectos.
    - **Profesor**: no se puede borrar si es **super admin** (primero hay que
      quitarle el rol con `PATCH /professors/{id}`) ni si está **asignado a algún
      curso lectivo** (**409**); primero hay que quitar la asignación.
    - En todos los casos se borran sus datos personales, su perfil, sus sesiones
      (refresh tokens) y sus códigos de contraseña pendientes; su legajo y su
      mail (si es profesor) quedan libres para volver a cargarlo.
    """
    await delete_user(db, id_user)
