from datetime import datetime
from typing import Literal

from pydantic import ConfigDict
from sqlmodel import SQLModel

from schemas.attendance import AttendanceStatsPublic
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


class StudentProjectAttendancePublic(StudentProjectMemberPublic):
    """Integrante con su porcentaje de asistencia en el curso lectivo."""

    attendance: AttendanceStatsPublic | None = None


class StudentProjectAttendanceList(SQLModel):
    id_project: int
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    group_number: int
    items: list[StudentProjectAttendancePublic]
    total: int
    limit: int
    offset: int
