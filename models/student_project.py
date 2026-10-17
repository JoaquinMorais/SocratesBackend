from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.status import Status


class StudentProject(SQLModel, table=True):
    __tablename__ = "student_projects"
    __table_args__ = (
        UniqueConstraint("id_student", "id_project", name="uq_student_project"),
    )

    id_student_project: int | None = Field(default=None, primary_key=True)
    id_student: int = Field(foreign_key="students.id_student", index=True)
    id_project: int = Field(foreign_key="projects.id_project", index=True)
    id_status: int = Field(foreign_key="statuses.id_status", index=True)

    status: Status = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
