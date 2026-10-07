from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from utils.security import hash_password, verify_password

if TYPE_CHECKING:
    from models.professor import Professor
    from models.student import Student


class UserBase(SQLModel):
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    legajo: int = Field(index=True)  # no es único
    birth_date: date


class User(UserBase, table=True):
    __tablename__ = "users"

    id_user: int | None = Field(default=None, primary_key=True)
    password_hash: str | None = Field(default=None, max_length=255)

    student: Optional["Student"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"uselist": False, "lazy": "selectin"},
    )
    professor: Optional["Professor"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"uselist": False, "lazy": "selectin"},
    )

    def get_mail(self) -> str:
        if self.student:
            return self.student.get_mail()
        if self.professor:
            return self.professor.get_mail()
        raise ValueError("User without student or professor profile")

    def set_password(self, password: str) -> None:
        self.password_hash = hash_password(password)

    def verify_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return verify_password(password, self.password_hash)