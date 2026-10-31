from datetime import date as date_type
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, field_validator
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
    state: str
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


MAX_ATTENDANCE_BULK = 200


class AttendanceBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_students: list[int] = PField(
        min_length=1, max_length=MAX_ATTENDANCE_BULK
    )

    @field_validator("id_students")
    @classmethod
    def positive_ids(cls, value: list[int]) -> list[int]:
        if any(id_student <= 0 for id_student in value):
            raise ValueError("id_students must be positive")
        return value


class AttendanceBulkResult(SQLModel):
    requested: int
    created: int
    already_present: int
    items: list[AttendancePublic] = Field(default_factory=list)
