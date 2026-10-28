from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.calendar_class import CalendarClass
from models.student_section_year import StudentSectionYear


class Attendance(SQLModel, table=True):
    """Asistencia de un alumno (su cursada) a una clase concreta.

    Solo hay fila cuando el alumno está presente; la ausencia es la falta de fila.
    """

    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint(
            "id_student_section_year",
            "id_calendar_class",
            name="uq_attendance_student_class",
        ),
        CheckConstraint(
            "method IN ('code', 'manual')", name="ck_attendance_method"
        ),
    )

    id_attendance: int | None = Field(default=None, primary_key=True)
    id_student_section_year: int = Field(
        foreign_key="student_section_years.id_student_section_year",
        index=True,
        ondelete="CASCADE",
    )
    id_calendar_class: int = Field(
        foreign_key="calendar_classes.id_calendar_class",
        index=True,
        ondelete="CASCADE",
    )
    method: str = Field(default="code", max_length=20)
    recorded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )

    student_section_year: StudentSectionYear = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    calendar_class: CalendarClass = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
