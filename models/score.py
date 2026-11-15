from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.section_year import SectionYear


class Score(SQLModel, table=True):
    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint("code", name="uq_score_code"),
        CheckConstraint(
            "default_value >= 1 AND default_value <= 100",
            name="ck_score_default_value",
        ),
    )

    id_score: int | None = Field(default=None, primary_key=True)
    code: str = Field(max_length=40)
    name: str = Field(max_length=100)
    sort_order: int = Field(default=0)
    default_value: int


class SectionYearScore(SQLModel, table=True):
    __tablename__ = "section_year_scores"
    __table_args__ = (
        UniqueConstraint(
            "id_section_year", "id_score", name="uq_section_year_score"
        ),
        CheckConstraint(
            "value >= 1 AND value <= 100", name="ck_section_year_score_value"
        ),
    )

    id_section_year_score: int | None = Field(default=None, primary_key=True)
    id_section_year: int = Field(
        foreign_key="section_years.id_section_year",
        index=True,
        ondelete="CASCADE",
    )
    id_score: int = Field(foreign_key="scores.id_score", index=True)
    value: int

    section_year: SectionYear = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    score: Score = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
