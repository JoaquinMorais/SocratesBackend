from datetime import date
from typing import Literal

from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel

Role = Literal["student", "professor"]


class UserPublic(SQLModel):
    id_user: int
    first_name: str
    last_name: str
    legajo: int
    email: str
    role: Role | None
    is_super_admin: bool | None = None  # solo profesores; en alumnos se omite


class UserUpdate(SQLModel):
    """Campos que el usuario puede modificar de sí mismo."""

    model_config = ConfigDict(extra="forbid")  # cualquier otro campo -> 422

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    birth_date: date | None = None

    @field_validator("birth_date")
    @classmethod
    def not_in_future(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("birth_date cannot be in the future")
        return v


class UserListItem(SQLModel):
    id_user: int
    first_name: str
    last_name: str
    legajo: int
    email: str
    role: Role | None
    enrollment_year: int | None = None  # solo alumnos
    is_super_admin: bool | None = None  # solo profesores


class UserList(SQLModel):
    items: list[UserListItem]
    total: int
    limit: int
    offset: int