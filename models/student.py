from sqlmodel import Field, Relationship, SQLModel

from models.user import User


class Student(SQLModel, table=True):
    __tablename__ = "students"

    id_student: int = Field(foreign_key="users.id_user", primary_key=True)
    enrollment_year: int

    user: User = Relationship(
        back_populates="student", sa_relationship_kwargs={"lazy": "selectin"}
    )