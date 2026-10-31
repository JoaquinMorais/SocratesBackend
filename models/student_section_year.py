from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field, Relationship, SQLModel

from models.section_year import SectionYear
from models.student import Student

# Estados de una fila del vínculo alumno + curso lectivo.
REGISTERED = "registered"  # anotado/inscripto (fila administrativa)
ATTENDING = "attending"  # cursada actual
ABANDONED = "abandoned"  # cursada abandonada/expulsada/cancelada
FINISHED_APPROVED = "finished_approved"  # finalizada y aprobada
FINISHED_FAILED = "finished_failed"  # finalizada y desaprobada
STATES = frozenset(
    {REGISTERED, ATTENDING, ABANDONED, FINISHED_APPROVED, FINISHED_FAILED}
)
CURRENT_CURSADA_STATES = frozenset({ATTENDING})
HISTORICAL_CURSADA_STATES = frozenset({ABANDONED, FINISHED_APPROVED, FINISHED_FAILED})


class StudentSectionYear(SQLModel, table=True):
    """Vínculo alumno + curso lectivo, con dos tipos de fila.

    - `registered`: la inscripción administrativa (una por alumno y año).
    - `attending`/`abandoned`/`finished_*`: la cursada académica (una actual por
      alumno y una fila de cursada por comisión). La inscripción y la cursada
      pueden convivir en la misma comisión como dos filas.
    """

    __tablename__ = "student_section_years"
    __table_args__ = (
        CheckConstraint(
            "state IN ('registered', 'attending', 'abandoned', "
            "'finished_approved', 'finished_failed')",
            name="ck_student_section_year_state",
        ),
        # Una inscripción por alumno y año.
        Index(
            "uq_student_section_year_registered",
            "id_student",
            "year",
            unique=True,
            postgresql_where=text("state = 'registered'"),
        ),
        # Una cursada actual por alumno.
        Index(
            "uq_student_section_year_attending",
            "id_student",
            unique=True,
            postgresql_where=text("state = 'attending'"),
        ),
        # Una fila de cursada por alumno y comisión (la inscripción es otra fila).
        Index(
            "uq_student_section_year_cursada",
            "id_student",
            "id_section_year",
            unique=True,
            postgresql_where=text("state <> 'registered'"),
        ),
    )

    id_student_section_year: int | None = Field(default=None, primary_key=True)
    id_student: int = Field(foreign_key="students.id_student", index=True)
    id_section_year: int = Field(
        foreign_key="section_years.id_section_year", index=True
    )
    year: int
    state: str = Field(default=REGISTERED, max_length=30)

    student: Student = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    section_year: SectionYear = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
