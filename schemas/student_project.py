from datetime import datetime
from typing import Literal

from pydantic import ConfigDict
from sqlmodel import SQLModel

from schemas.status import StatusPublic

# Decisiones que puede tomar el jefe de un grupo sobre una solicitud.
MembershipDecision = Literal["active", "rejected"]


class StudentProjectPublic(SQLModel):
    id_student_project: int
    id_project: int
    id_student: int
    is_leader: bool
    enrolled_at: datetime
    status: StatusPublic


class StudentProjectMemberPublic(SQLModel):
    """Integrante de un grupo, con los datos públicos del alumno (sin mail)."""

    id_student_project: int
    id_student: int
    first_name: str
    last_name: str
    legajo: int
    is_leader: bool
    enrolled_at: datetime
    status: StatusPublic


class StudentProjectList(SQLModel):
    items: list[StudentProjectMemberPublic]
    total: int
    limit: int
    offset: int


class StudentProjectUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    # Solo el jefe acepta (`active`) o rechaza (`rejected`) una solicitud.
    status: MembershipDecision
