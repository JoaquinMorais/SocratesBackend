from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.section_year import SectionYear


class Calendar(SQLModel, table=True):
    """Calendario de un curso lectivo (relación 1 a 1).

    Las clases concretas cuelgan de acá. Un curso lectivo tiene exactamente un
    calendario; se crea junto con el curso (o al primer acceso, para datos viejos).
    """

    __tablename__ = "calendars"
    __table_args__ = (
        UniqueConstraint("id_section_year", name="uq_calendar_section_year"),
    )

    id_calendar: int | None = Field(default=None, primary_key=True)
    id_section_year: int = Field(
        foreign_key="section_years.id_section_year", index=True, ondelete="CASCADE"
    )
    # Informativo por ahora: las horas de las clases son hora de pared.
    timezone: str = Field(default="America/Argentina/Buenos_Aires", max_length=50)

    section_year: SectionYear = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
