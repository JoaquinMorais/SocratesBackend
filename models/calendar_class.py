from datetime import date as date_type
from datetime import time

from sqlalchemy import CheckConstraint, Time, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.calendar import Calendar


class CalendarClass(SQLModel, table=True):
    """Una clase concreta del calendario de un curso lectivo.

    Una fila por fecha real (no una regla semanal): las excepciones y feriados se
    manejan editando o borrando la fila. `weekday` se deriva de `date`.
    """

    __tablename__ = "calendar_classes"
    __table_args__ = (
        UniqueConstraint(
            "id_calendar", "date", "start_time", name="uq_calendar_class_slot"
        ),
        CheckConstraint(
            "end_time > start_time", name="ck_calendar_class_time_range"
        ),
        CheckConstraint(
            "modality IN ('in_person', 'virtual')",
            name="ck_calendar_class_modality",
        ),
    )

    id_calendar_class: int | None = Field(default=None, primary_key=True)
    id_calendar: int = Field(
        foreign_key="calendars.id_calendar", index=True, ondelete="CASCADE"
    )
    date: date_type = Field(index=True)
    start_time: time = Field(sa_type=Time)
    end_time: time = Field(sa_type=Time)
    modality: str = Field(default="in_person", max_length=20)
    title: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    meeting_url: str | None = Field(default=None, max_length=500)

    calendar: Calendar = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
