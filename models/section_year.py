from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.section import Section


class SectionYear(SQLModel, table=True):
    __tablename__ = "section_years"
    __table_args__ = (UniqueConstraint("year", "id_section", name="uq_section_year"),)

    id_section_year: int | None = Field(default=None, primary_key=True)
    year: int = Field(index=True)
    id_section: int = Field(foreign_key="sections.id_section", index=True)

    section: Section = Relationship(sa_relationship_kwargs={"lazy": "selectin"})