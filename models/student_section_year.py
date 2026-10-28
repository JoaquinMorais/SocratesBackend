from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.section_year import SectionYear
from models.student import Student


class StudentSectionYear(SQLModel, table=True):
    """Cursada: un alumno en un curso lectivo (comisión + año).

    Un alumno puede haber cursado varios años lectivos a lo largo del tiempo y un
    curso lectivo tiene muchos alumnos. Guarda solo el vínculo; se le pueden sumar
    atributos (estado de cursada, notas, etc.) sin rehacer la tabla.
    """

    __tablename__ = "student_section_years"
    __table_args__ = (
        UniqueConstraint(
            "id_student", "id_section_year", name="uq_student_section_year"
        ),
        # Un alumno no puede tener dos cursadas del mismo año (dos comisiones en
        # el mismo año). `year` es una copia de `section_year.year` que existe
        # solo para poder expresar esta restricción en la BD.
        UniqueConstraint("id_student", "year", name="uq_student_section_year_year"),
    )

    id_student_section_year: int | None = Field(default=None, primary_key=True)
    id_student: int = Field(foreign_key="students.id_student", index=True)
    id_section_year: int = Field(
        foreign_key="section_years.id_section_year", index=True
    )
    year: int

    student: Student = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    section_year: SectionYear = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
