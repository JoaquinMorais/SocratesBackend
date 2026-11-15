from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.delivery_comment import (
    CommentKind,
    DeliveryCommentCreate,
    DeliveryCommentList,
    DeliveryCommentPublic,
    DeliveryCommentUpdate,
)
from utils.auth import user_dependency
from models.state.delivery_comment import ANNOTATION_KIND
from utils.delivery_comments import (
    correct_comment,
    create_comment,
    get_comment_public,
    list_all_comments,
    list_comments,
    update_comment,
)
from utils.permissions import professor_dependency
from utils.projects import build_access

delivery_comments_router = APIRouter(tags=["delivery-comments"])

_AUTH_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}
_DELIVERY_ERRORS = {
    **_AUTH_ERRORS,
    403: {"description": "El usuario no puede ver los comentarios de esa entrega"},
    404: {"description": "No existe la entrega"},
}
_COMMENT_ERRORS = {
    **_AUTH_ERRORS,
    403: {"description": "El usuario no puede ver ese comentario"},
    404: {"description": "No existe el comentario"},
}


@delivery_comments_router.post(
    "/deliveries/{id_delivery}/comments",
    response_model=DeliveryCommentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un comentario de entrega",
    responses={
        **_DELIVERY_ERRORS,
        422: {"description": "Contenido vacío, demasiado largo o campos desconocidos"},
    },
)
async def create_delivery_comment_route(
    id_delivery: int,
    data: DeliveryCommentCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Crea un comentario sobre una entrega. **Profesor del curso o super admin.**

    - `kind=feedback` (por defecto): feedback para el grupo; nace `requested` y
      puede marcarse `corrected`.
    - `kind=annotation`: anotación interna; nace `annotation` y solo la ve el
      staff del curso.
    - `content` se recorta y no puede quedar vacío.
    - La entrega debe existir (**404**).
    """
    access = await build_access(db, user)
    return await create_comment(db, access, user.id_user, id_delivery, data)


@delivery_comments_router.get(
    "/deliveries/{id_delivery}/comments",
    response_model=DeliveryCommentList,
    summary="Listar los comentarios de una entrega",
    responses=_DELIVERY_ERRORS,
)
async def list_delivery_comments_route(
    id_delivery: int,
    db: db_dependency,
    user: user_dependency,
    kind: Annotated[
        CommentKind | None,
        Query(description="Filtrar por tipo (solo el staff puede pedir annotation)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los comentarios de una entrega, más nuevos primero. **Integrantes
    `active`/`finished`, profesor del curso o super admin.**

    - Los alumnos solo ven `feedback`; las anotaciones son internas del staff.
    - El staff puede filtrar con `kind` y ve ambos tipos.
    - Está paginado: `total` es la cantidad que cumple el filtro.
    """
    access = await build_access(db, user)
    return await list_comments(
        db,
        access,
        id_delivery,
        kind=kind,
        limit=limit,
        offset=offset,
    )


@delivery_comments_router.get(
    "/delivery-comments",
    response_model=DeliveryCommentList,
    summary="Buscar comentarios y anotaciones",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El profesor no está asignado al curso consultado"},
        404: {"description": "No existe el proyecto, la actividad o la entrega"},
        422: {"description": "Filtros inválidos o `q` vacío"},
    },
)
async def search_delivery_comments_route(
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    kind: Annotated[
        CommentKind | None,
        Query(description="Filtrar por `feedback` o `annotation`"),
    ] = None,
    id_project: Annotated[
        int | None, Query(gt=0, description="Anotaciones/comentarios del proyecto")
    ] = None,
    id_activity: Annotated[
        int | None, Query(gt=0, description="Anotaciones/comentarios de la actividad")
    ] = None,
    id_delivery: Annotated[
        int | None, Query(gt=0, description="Anotaciones/comentarios de la entrega")
    ] = None,
    id_professor: Annotated[
        int | None, Query(gt=0, description="Filtrar por profesor autor")
    ] = None,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=2000, description="Busca dentro del contenido"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Busca comentarios y anotaciones con contexto de proyecto y actividad. **Solo
    profesor del curso o super admin.**

    - Un profesor común solo ve los comentarios de los cursos lectivos que dicta;
      el super admin ve todos.
    - Filtros: `kind`, `id_project`, `id_activity`, `id_delivery`, `id_professor`
      y `q` (texto dentro del contenido, sin distinguir mayúsculas).
    - Un proyecto/actividad/entrega fuera de los cursos del profesor responde
      **403**; uno inexistente, **404**.
    - Orden más nuevo primero; paginado con `total`.
    """
    access = await build_access(db, user)
    return await list_all_comments(
        db,
        access,
        kind=kind,
        id_project=id_project,
        id_activity=id_activity,
        id_delivery=id_delivery,
        id_professor=id_professor,
        q=q,
        limit=limit,
        offset=offset,
    )


@delivery_comments_router.get(
    "/projects/{id_project}/annotations",
    response_model=DeliveryCommentList,
    summary="Listar las anotaciones de un proyecto",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El profesor no está asignado al curso del proyecto"},
        404: {"description": "No existe el proyecto"},
        422: {"description": "`q` vacío o paginación inválida"},
    },
)
async def list_project_annotations_route(
    id_project: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=2000, description="Busca dentro del contenido"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista todas las **anotaciones internas** del proyecto, de todas sus
    actividades. **Profesor del curso o super admin.**

    - Solo devuelve `kind=annotation`; el feedback no se incluye.
    - `q` busca dentro del contenido.
    - Orden más nuevo primero; paginado.
    """
    access = await build_access(db, user)
    return await list_all_comments(
        db,
        access,
        kind=ANNOTATION_KIND,
        id_project=id_project,
        id_activity=None,
        id_delivery=None,
        id_professor=None,
        q=q,
        limit=limit,
        offset=offset,
    )


@delivery_comments_router.get(
    "/activities/{id_activity}/annotations",
    response_model=DeliveryCommentList,
    summary="Listar las anotaciones de una actividad",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El profesor no está asignado al curso de la actividad"},
        404: {"description": "No existe la actividad"},
        422: {"description": "`q` vacío o paginación inválida"},
    },
)
async def list_activity_annotations_route(
    id_activity: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=2000, description="Busca dentro del contenido"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista todas las **anotaciones internas** de una actividad, de todos los
    proyectos. **Profesor del curso o super admin.**

    - Solo devuelve `kind=annotation`; el feedback no se incluye.
    - `q` busca dentro del contenido.
    - Orden más nuevo primero; paginado.
    """
    access = await build_access(db, user)
    return await list_all_comments(
        db,
        access,
        kind=ANNOTATION_KIND,
        id_project=None,
        id_activity=id_activity,
        id_delivery=None,
        id_professor=None,
        q=q,
        limit=limit,
        offset=offset,
    )


@delivery_comments_router.get(
    "/delivery-comments/{id_delivery_comment}",
    response_model=DeliveryCommentPublic,
    summary="Consultar un comentario de entrega",
    responses=_COMMENT_ERRORS,
)
async def get_delivery_comment_route(
    id_delivery_comment: int, db: db_dependency, user: user_dependency
):
    """
    Devuelve un comentario. **Integrantes `active`/`finished`, profesor del
    curso o super admin.**

    Las anotaciones internas solo las puede consultar el staff; para un alumno
    responden **403**.
    """
    access = await build_access(db, user)
    return await get_comment_public(db, access, id_delivery_comment)


@delivery_comments_router.patch(
    "/delivery-comments/{id_delivery_comment}",
    response_model=DeliveryCommentPublic,
    summary="Editar un comentario de entrega",
    responses={
        **_COMMENT_ERRORS,
        409: {
            "description": (
                "Un feedback corregido no se puede editar; una anotación no cambia "
                "de estado"
            )
        },
        422: {"description": "Body vacío, contenido inválido o campos desconocidos"},
    },
)
async def update_delivery_comment_route(
    id_delivery_comment: int,
    data: DeliveryCommentUpdate,
    db: db_dependency,
    user: user_dependency,
):
    """
    Edita el contenido de un comentario. **Solo el profesor autor.**

    - Un `feedback` solo lo edita su autor y mientras está `requested`.
    - Una `annotation` la puede editar cualquier profesor actualmente asignado al
      curso o un super admin; su estado no cambia.
    - No se puede cambiar autor, entrega, `kind` ni estado.
    """
    access = await build_access(db, user)
    return await update_comment(
        db, access, user.id_user, id_delivery_comment, data
    )


@delivery_comments_router.post(
    "/delivery-comments/{id_delivery_comment}/correct",
    response_model=DeliveryCommentPublic,
    summary="Marcar un comentario como corregido",
    responses={
        **_COMMENT_ERRORS,
        409: {"description": "El comentario ya está corregido o es una anotación"},
    },
)
async def correct_delivery_comment_route(
    id_delivery_comment: int, db: db_dependency, user: user_dependency
):
    """
    Marca un `feedback` como `corrected`. **Integrante `active`/`finished`,
    profesor del curso o super admin.**

    - Solo aplica a comentarios `kind=feedback`.
    - Setea `corrected_at`; el estado `corrected` es final.
    - Repetir la acción o intentarlo sobre una `annotation` responde **409**.
    """
    access = await build_access(db, user)
    return await correct_comment(db, access, id_delivery_comment)
