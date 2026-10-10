from sqlalchemy import CheckConstraint, Column, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.section_year import SectionYear


class Project(SQLModel, table=True):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("id_section_year", "group_number", name="uq_project_group"),
        CheckConstraint(
            "privacy IN ('public', 'private', 'protected')", name="ck_project_privacy"
        ),
    )

    id_project: int | None = Field(default=None, primary_key=True)
    id_section_year: int = Field(foreign_key="section_years.id_section_year", index=True)
    group_number: int
    privacy: str = Field(default="private", max_length=20)

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    objective: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    problem: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    section_year: SectionYear = Relationship(sa_relationship_kwargs={"lazy": "selectin"})