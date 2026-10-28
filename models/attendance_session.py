from datetime import datetime, timezone

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.calendar_class import CalendarClass


class AttendanceSession(SQLModel, table=True):
    """Toma de asistencia de una clase concreta.

    Una sola sesión por clase: al abrirla (o reabrirla) se genera un código nuevo
    y se reinicia el vencimiento. El código se guarda hasheado.
    """

    __tablename__ = "attendance_sessions"
    __table_args__ = (
        UniqueConstraint(
            "id_calendar_class", name="uq_attendance_session_class"
        ),
    )

    id_attendance_session: int | None = Field(default=None, primary_key=True)
    id_calendar_class: int = Field(
        foreign_key="calendar_classes.id_calendar_class",
        index=True,
        ondelete="CASCADE",
    )
    code_hash: str = Field(max_length=64)
    opened_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))
    closed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )

    calendar_class: CalendarClass = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
