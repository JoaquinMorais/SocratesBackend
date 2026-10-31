from datetime import date as date_type
from datetime import time

from sqlalchemy import Column, Text, Time
from sqlmodel import Field, Relationship, SQLModel

from models.calendar import Calendar


class Activity(SQLModel, table=True):
    """Actividad/entrega del curso lectivo, con fecha de entrega.

    Es del calendario (y por lo tanto del curso lectivo completo): todos los
    alumnos del curso la ven. El vínculo con un proyecto ("entregable") se
    resolverá más adelante con otra relación.
    """

    __tablename__ = "activities"

    id_activity: int | None = Field(default=None, primary_key=True)
    id_calendar: int = Field(
        foreign_key="calendars.id_calendar", index=True, ondelete="CASCADE"
    )
    title: str = Field(max_length=200)
    description: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    due_date: date_type = Field(index=True)
    due_time: time | None = Field(default=None, sa_type=Time)
    link_required: bool = Field(default=False)

    calendar: Calendar = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
