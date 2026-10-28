from sqlmodel import Field, SQLModel

from schemas.activity import ActivityPublic
from schemas.calendar_class import CalendarClassPublic
from schemas.section_year import SectionYearPublic


class MyCalendarPublic(SQLModel):
    """Respuesta de `GET /me/calendar`: clases y actividades de mis cursos actuales."""

    section_years: list[SectionYearPublic] = Field(default_factory=list)
    classes: list[CalendarClassPublic] = Field(default_factory=list)
    activities: list[ActivityPublic] = Field(default_factory=list)
