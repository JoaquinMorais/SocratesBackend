from sqlmodel import Field, Relationship, SQLModel

from models.user import User


class Professor(SQLModel, table=True):
    __tablename__ = "professors"

    id_professor: int = Field(foreign_key="users.id_user", primary_key=True)

    user: User = Relationship(
        back_populates="professor", sa_relationship_kwargs={"lazy": "selectin"}
    )