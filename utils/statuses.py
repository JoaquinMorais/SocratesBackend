from fastapi import HTTPException, status
from sqlmodel import col, func, select

from models import Status
from models.state import (
    MEMBER_CODES,
    PROJECT_CATALOG,
    PROJECT_INITIAL,
    PROJECT_INSURED,
    STUDENT_PROJECT_CATALOG,
    STUDENT_SECTION_YEAR_CATALOG,
    STUDENT_PROJECT_INITIAL,
    STUDENT_PROJECT_PENDING,
    state_for,
)
from schemas.status import StatusPublic


def is_member(code: str) -> bool:
    """Si un código de membresía cuenta como 'pertenece al grupo'."""
    return code in MEMBER_CODES


def is_insured(code: str) -> bool:
    """Si un código de proyecto cuenta como 'insured' (asegurado)."""
    return code in PROJECT_INSURED


# Estados que se crean al arrancar para que siempre exista al menos el inicial.
# La seed puede sumar más; estos no se borran.
DEFAULT_STATUSES = [
    {
        "ambito": state.ambito,
        "code": state.code,
        "name": state.name,
        "description": state.description,
        "is_final": state.is_final,
    }
    for state in (
        *PROJECT_CATALOG,
        *STUDENT_PROJECT_CATALOG,
        *STUDENT_SECTION_YEAR_CATALOG,
    )
]


def membership_initial_status(has_leader: bool) -> str:
    """Estado inicial de una membresía nueva: con jefe en el grupo, queda pendiente."""
    return STUDENT_PROJECT_PENDING if has_leader else STUDENT_PROJECT_INITIAL


def to_public(status: Status) -> StatusPublic:
    return StatusPublic(
        id_status=status.id_status,
        ambito=status.ambito,
        code=status.code,
        name=status.name,
        description=status.description,
        is_final=status.is_final,
        is_insured=state_for(status).is_insured,
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
