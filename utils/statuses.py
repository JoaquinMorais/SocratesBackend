from collections.abc import Mapping
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlmodel import col, func, select

from models import Status
from schemas.status import StatusPublic

# Categorías que puede tener un estado, por ámbito.
MEMBER = "member"  # student_project: el alumno pertenece al grupo (`active`, `finished`).


@dataclass(frozen=True)
class StatusPolicy:
    """Reglas de un ámbito: estado inicial, orden, categorías y transiciones.

    Las categorías agrupan códigos (por ejemplo `member` = `active` y `finished`);
    las transiciones dicen qué estados admite cada estado. Viven en código porque
    son reglas de dominio estables: la seed puede sumar estados, pero no cambia
    estas reglas. La categoría `insured` del ámbito `project` se sumará cuando
    existan esos estados.
    """

    ambito: str
    initial: str
    order: tuple[str, ...]
    categories: Mapping[str, frozenset[str]] = field(default_factory=dict)
    pending: str | None = None
    transitions: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def has(self, code: str, category: str) -> bool:
        """Si el código `code` pertenece a `category`."""
        return code in self.categories.get(category, frozenset())

    def codes_of(self, category: str) -> frozenset[str]:
        """Códigos de `category`, para usar en un `IN` de SQL."""
        return self.categories.get(category, frozenset())

    def next_codes(self, code: str) -> frozenset[str]:
        """Estados a los que se puede pasar desde `code` (vacío si es terminal)."""
        return self.transitions.get(code, frozenset())

    def can_transition(self, from_code: str, to_code: str) -> bool:
        """Si se puede pasar de `from_code` a `to_code`."""
        return to_code in self.next_codes(from_code)


STUDENT_PROJECT = StatusPolicy(
    ambito="student_project",
    initial="active",
    pending="pending_approval",
    order=(
        "active",
        "pending_approval",
        "finished",
        "abandoned",
        "expelled",
        "rejected",
    ),
    categories={MEMBER: frozenset({"active", "finished"})},
    transitions={
        "pending_approval": frozenset({"active", "rejected"}),
        "active": frozenset({"abandoned", "expelled", "finished"}),
        "rejected": frozenset({"pending_approval"}),
    },
)

PROJECT = StatusPolicy(
    ambito="project",
    initial="active",
    order=("active", "cancelled"),
)

POLICIES = {policy.ambito: policy for policy in (PROJECT, STUDENT_PROJECT)}


def is_member(code: str) -> bool:
    """Si un código de membresía cuenta como 'pertenece al grupo'."""
    return STUDENT_PROJECT.has(code, MEMBER)


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
    return STUDENT_PROJECT.pending if has_leader else STUDENT_PROJECT.initial


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
