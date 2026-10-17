from typing import Literal

from sqlmodel import SQLModel

Ambito = Literal["project", "student_project"]

MembershipStatus = Literal[
    "active",
    "pending_approval",
    "abandoned",
    "finished",
    "expelled",
    "rejected",
]


class StatusPublic(SQLModel):
    id_status: int
    ambito: str
    code: str
    name: str
    description: str | None = None
    is_final: bool


class StatusList(SQLModel):
    items: list[StatusPublic]
    total: int
    limit: int
    offset: int
