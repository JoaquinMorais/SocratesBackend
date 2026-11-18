from datetime import date as date_type
from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Index, Text, text
from sqlmodel import Field, Relationship, SQLModel

from models.section_year import SectionYear


class StudentEvaluation(SQLModel, table=True):
    """Evaluación/parcial de un curso lectivo, independiente de los proyectos."""

    __tablename__ = "student_evaluations"
    __table_args__ = (
        Index(
            "uq_student_evaluations_name",
            "id_section_year",
            text("lower(name)"),
            unique=True,
        ),
    )

    id_student_evaluation: int | None = Field(default=None, primary_key=True)
    id_section_year: int = Field(
        foreign_key="section_years.id_section_year",
        index=True,
        ondelete="CASCADE",
    )
    name: str = Field(max_length=200)
    description: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    date: date_type = Field(sa_type=Date)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )

    section_year: SectionYear = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
