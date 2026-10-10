from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class StudentProject(SQLModel, table=True):
    __tablename__ = "student_projects"
    __table_args__ = (
        UniqueConstraint("id_student", "id_project", name="uq_student_project"),
    )

    id_student_project: int | None = Field(default=None, primary_key=True)
    id_student: int = Field(foreign_key="students.id_student", index=True)
    id_project: int = Field(foreign_key="projects.id_project", index=True)