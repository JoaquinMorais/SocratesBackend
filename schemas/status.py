from typing import Literal

from sqlmodel import SQLModel

Ambito = Literal["project", "student_project", "student_section_year"]

MembershipStatus = Literal[
    "active",
    "pending_approval",
    "abandoned",
    "finished",
    "expelled",
    "rejected",
]

ProjectStatus = Literal[
    "uninsured",
    "in_idea",
    "in_progress",
    "pending_approval",
    "rejected",
    "approved",
    "cancelled",
]


class StatusPublic(SQLModel):
    id_status: int
    ambito: str
    code: str
    name: str
    description: str | None = None
    is_final: bool
    is_insured: bool = False


class StatusList(SQLModel):
    items: list[StatusPublic]
    total: int
    limit: int
    offset: int
