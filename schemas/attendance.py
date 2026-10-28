from datetime import date as date_type
from datetime import datetime, time

from pydantic import ConfigDict, field_validator
from pydantic import Field as PField
from sqlmodel import Field, SQLModel


class AttendanceCheckIn(SQLModel):
    model_config = ConfigDict(extra="forbid")

    code: str = PField(min_length=6, max_length=6, pattern=r"^\d{6}$")

    @field_validator("code", mode="before")
    @classmethod
    def strip_code(cls, v):
        return v.strip() if isinstance(v, str) else v


class AttendanceSessionOpenedPublic(SQLModel):
    """Código recién generado: solo se muestra al abrir/rotar la toma."""

    id_attendance_session: int
    id_calendar_class: int
    code: str
    expires_at: datetime


class AttendanceSessionStatusPublic(SQLModel):
    id_attendance_session: int
    open: bool
    opened_at: datetime
    expires_at: datetime
    closed_at: datetime | None = None


class AttendanceStudentPublic(SQLModel):
    id_student_section_year: int
    id_student: int
    first_name: str
    last_name: str
    legajo: int
    present: bool
    method: str | None = None
    recorded_at: datetime | None = None


class ClassAttendancePublic(SQLModel):
    session: AttendanceSessionStatusPublic | None = None
    items: list[AttendanceStudentPublic] = Field(default_factory=list)


class AttendancePublic(SQLModel):
    id_attendance: int
    id_calendar_class: int
    id_student_section_year: int
    id_student: int
    id_section_year: int
    method: str
    recorded_at: datetime


class MyAttendanceItemPublic(SQLModel):
    id_attendance: int
    id_calendar_class: int
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    date: date_type
    start_time: time
    end_time: time
    title: str | None = None
    modality: str
    method: str
    recorded_at: datetime


class MyAttendanceListPublic(SQLModel):
    items: list[MyAttendanceItemPublic] = Field(default_factory=list)
