from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.professor import Professor
from models.section_year import SectionYear


class ProfessorSectionYear(SQLModel, table=True):
    __tablename__ = "professor_section_years"
    __table_args__ = (
        UniqueConstraint("id_professor", "id_section_year", name="uq_professor_section_year"),
    )

    id_professor_section_year: int | None = Field(default=None, primary_key=True)
    id_professor: int = Field(foreign_key="professors.id_professor", index=True)
    id_section_year: int = Field(foreign_key="section_years.id_section_year", index=True)

    professor: Professor = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    section_year: SectionYear = Relationship(sa_relationship_kwargs={"lazy": "selectin"})