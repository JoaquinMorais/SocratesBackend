from fastapi import HTTPException, status
from sqlmodel import col, func, select

from models import Status
from schemas.status import StatusPublic

# Estado con el que nacen las entidades, por ámbito.
INITIAL_STATUS = {"project": "active", "student_project": "active"}

# Estado de una membresía que se une a un grupo que ya tiene jefe.
PENDING_STATUS = "pending_approval"

# Estados de una membresía que cuentan como "pertenece al grupo" para los
# privilegios: ver el detalle de un proyecto protegido y acceder a uno privado.
PRIVILEGED_STATUSES = ("active", "finished")

# Estados de membresía que se listan en `GET /students` si no se pide otro filtro.
DEFAULT_MEMBERSHIP_STATUSES = ["active", "finished"]

# Orden en que se agrupan los grupos de un alumno según el estado de la membresía.
MEMBERSHIP_STATUS_ORDER = [
    "active",
    "pending_approval",
    "finished",
    "abandoned",
    "expelled",
    "rejected",
]

# Estados que se crean al arrancar para que siempre exista al menos el inicial.
# La seed puede sumar más; estos no se borran.
DEFAULT_STATUSES = [
    {
        "ambito": "project",
        "code": "active",
        "name": "Activo",
        "description": "El grupo está en curso.",
        "is_final": False,
    },
    {
        "ambito": "project",
        "code": "cancelled",
        "name": "Cancelado",
        "description": "El grupo se disolvió o el proyecto no se llevó a cabo.",
        "is_final": True,
    },
    {
        "ambito": "student_project",
        "code": "active",
        "name": "Activo",
        "description": "El alumno integra el grupo.",
        "is_final": False,
    },
    {
        "ambito": "student_project",
        "code": "pending_approval",
        "name": "Pendiente de aprobación",
        "description": "El alumno solicitó unirse y espera la aprobación de un profesor.",
        "is_final": False,
    },
    {
        "ambito": "student_project",
        "code": "abandoned",
        "name": "Abandono",
        "description": "El alumno dejó el grupo antes de terminar el cursado.",
        "is_final": True,
    },
    {
        "ambito": "student_project",
        "code": "finished",
        "name": "Finalizado",
        "description": "El proyecto terminó y la participación quedó cerrada.",
        "is_final": True,
    },
    {
        "ambito": "student_project",
        "code": "expelled",
        "name": "Expulsado",
        "description": "Un profesor sacó al alumno del grupo.",
        "is_final": True,
    },
    {
        "ambito": "student_project",
        "code": "rejected",
        "name": "Rechazado",
        "description": "La solicitud de incorporación fue rechazada.",
        "is_final": False,
    },
]


def membership_initial_status(has_leader: bool) -> str:
    """Estado inicial de una membresía nueva: con jefe en el grupo, queda pendiente."""
    return PENDING_STATUS if has_leader else INITIAL_STATUS["student_project"]


def to_public(status: Status) -> StatusPublic:
    return StatusPublic(
        id_status=status.id_status,
        ambito=status.ambito,
        code=status.code,
        name=status.name,
        description=status.description,
        is_final=status.is_final,
    )


async def get_status(db, ambito: str, code: str) -> Status:
    """Devuelve el estado `(ambito, code)`; 404 si no existe o no es de ese ámbito."""
    found = (
        await db.exec(
            select(Status).where(Status.ambito == ambito, Status.code == code)
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Status not found")
    return found


async def ensure_statuses(db, items: list[dict] | None = None) -> dict[tuple[str, str], Status]:
    """Crea los estados que falten y devuelve el índice por `(ambito, code)`."""
    every = {(s.ambito, s.code): s for s in (await db.exec(select(Status))).all()}
    for item in DEFAULT_STATUSES if items is None else items:
        key = (item["ambito"], item["code"])
        if key not in every:
            status = Status(**item)
            db.add(status)
            every[key] = status
    await db.flush()
    return every


async def list_statuses(
    db, *, ambito: str | None, limit: int, offset: int
) -> tuple[list[Status], int]:
    conditions = []
    if ambito is not None:
        conditions.append(Status.ambito == ambito)
    total = (
        await db.exec(select(func.count()).select_from(Status).where(*conditions))
    ).one()
    items = (
        await db.exec(
            select(Status)
            .where(*conditions)
            .order_by(col(Status.ambito), col(Status.id_status))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total
