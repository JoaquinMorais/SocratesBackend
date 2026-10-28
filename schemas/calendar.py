from sqlmodel import Field, SQLModel

from schemas.activity import ActivityPublic
from schemas.calendar_class import CalendarClassPublic


class CalendarPublic(SQLModel):
    id_calendar: int
    id_section_year: int
    timezone: str


class CalendarWithClassesPublic(CalendarPublic):
    """Calendario del curso lectivo: clases concretas y actividades."""

    classes: list[CalendarClassPublic] = Field(default_factory=list)
    activities: list[ActivityPublic] = Field(default_factory=list)
