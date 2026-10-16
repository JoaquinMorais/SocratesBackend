from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.section import Section


class SectionYear(SQLModel, table=True):
    __tablename__ = "section_years"
    __table_args__ = (
        UniqueConstraint("year", "id_section", name="uq_section_year"),
        CheckConstraint("min_students >= 1", name="ck_section_year_min_students"),
        CheckConstraint("max_students <= 100", name="ck_section_year_max_students"),
        CheckConstraint("max_students >= min_students", name="ck_section_year_group_size"),
    )

    id_section_year: int | None = Field(default=None, primary_key=True)
    year: int = Field(index=True)
    id_section: int = Field(foreign_key="sections.id_section", index=True)
    min_students: int
    max_students: int

    section: Section = Relationship(sa_relationship_kwargs={"lazy": "selectin"})