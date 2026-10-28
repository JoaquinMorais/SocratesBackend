from sqlmodel import Field, SQLModel

from schemas.section_year import SectionYearPublic


class MySectionYearsPublic(SQLModel):
    """Respuesta de `GET /me/section-year`: mis cursos lectivos del año máximo.

    Un alumno tiene a lo sumo uno (no puede cursar dos comisiones del mismo año);
    un profesor puede tener varios si dicta más de una comisión de ese año.
    """

    section_years: list[SectionYearPublic] = Field(default_factory=list)
