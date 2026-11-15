from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel

from models.section import Section


class SectionYear(SQLModel, table=True):
    __tablename__ = "section_years"
    __table_args__ = (
        UniqueConstraint("year", "id_section", name="uq_section_year"),
        CheckConstraint("min_students >= 1", name="ck_section_year_min_students"),
        CheckConstraint("max_students <= 100", name="ck_section_year_max_students"),
        CheckConstraint("max_students >= min_students", name="ck_section_year_group_size"),
        Index(
            "uq_section_years_generic",
            "is_generic",
            unique=True,
            postgresql_where=text("is_generic"),
        ),
    )

    id_section_year: int | None = Field(default=None, primary_key=True)
    year: int = Field(index=True)
    id_section: int = Field(foreign_key="sections.id_section", index=True)
    min_students: int
    max_students: int
    # Habilita reintentar un curso lectivo cuya cursada quedó `finished_failed`.
    allow_project_joins: bool = Field(default=False)
    # Habilita que los alumnos entreguen actividades de este curso lectivo.
    allow_student_submissions: bool = Field(default=False)
    is_generic: bool = Field(default=False)

    section: Section = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
