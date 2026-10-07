from sqlmodel import Field, Relationship, SQLModel

from models.user import User


class Professor(SQLModel, table=True):
    __tablename__ = "professors"

    id_professor: int = Field(foreign_key="users.id_user", primary_key=True)
    mail: str = Field(unique=True, index=True, max_length=255)
    is_super_admin: bool = Field(default=False)

    user: User = Relationship(
        back_populates="professor", sa_relationship_kwargs={"lazy": "selectin"}
    )

    def get_mail(self) -> str:
        return self.mail