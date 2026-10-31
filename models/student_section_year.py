from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field, Relationship, SQLModel

from models.section_year import SectionYear
from models.status import Status
from models.student import Student

from models.state.student_section_year import REGISTERED


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
    id_status: int = Field(foreign_key="statuses.id_status", index=True)
    # Espejo de `status.code`: se mantiene para los índices parciales.
    state: str = Field(default=REGISTERED, max_length=30)

    status: Status = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    student: Student = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    section_year: SectionYear = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
