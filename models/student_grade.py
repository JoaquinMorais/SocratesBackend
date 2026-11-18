from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.student_evaluation import StudentEvaluation
from models.student_section_year import StudentSectionYear


class StudentGrade(SQLModel, table=True):
    """Nota de un alumno en una evaluación del curso lectivo."""

    __tablename__ = "student_grades"
    __table_args__ = (
        CheckConstraint(
            "grade >= 0 AND grade <= 10", name="ck_student_grade_value"
        ),
        UniqueConstraint(
            "id_student_evaluation",
            "id_student_section_year",
            name="uq_student_grade_evaluation_cursada",
        ),
    )

    id_student_grade: int | None = Field(default=None, primary_key=True)
    id_student_evaluation: int = Field(
        foreign_key="student_evaluations.id_student_evaluation",
        index=True,
        ondelete="CASCADE",
    )
    id_student_section_year: int = Field(
        foreign_key="student_section_years.id_student_section_year",
        index=True,
        ondelete="CASCADE",
    )
    grade: int = Field(default=0)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )

    evaluation: StudentEvaluation = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    student_section_year: StudentSectionYear = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
