from datetime import date
from typing import Literal

from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel

Role = Literal["student", "professor"]

MIN_AGE = 18


def ensure_adult(birth_date: date) -> date:
    """Valida que el usuario tenga al menos MIN_AGE años (edad a hoy)."""
    today = date.today()
    age = (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )
    if age < MIN_AGE:
        raise ValueError("birth_date must make the user at least 18 years old")
    return birth_date


class UserPublic(SQLModel):
    id_user: int
    first_name: str
    last_name: str
    legajo: int
    email: str
    role: Role | None
    birth_date: date | None = None
    enrollment_year: int | None = None  # solo alumnos
    age: int | None = None
    is_super_admin: bool | None = None  # solo profesores; en alumnos se omite


class UserUpdate(SQLModel):
    """Campos que el usuario puede modificar de sí mismo."""

    model_config = ConfigDict(extra="forbid")  # cualquier otro campo -> 422

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    birth_date: date | None = None

    @field_validator("birth_date")
    @classmethod
    def is_adult(cls, v: date | None) -> date | None:
        return None if v is None else ensure_adult(v)


class UserListItem(SQLModel):
    id_user: int
    first_name: str
    last_name: str
    legajo: int
    email: str
    role: Role | None
    birth_date: date | None = None
    enrollment_year: int | None = None  # solo alumnos
    age: int | None = None
    is_super_admin: bool | None = None  # solo profesores


class UserList(SQLModel):
    items: list[UserListItem]
    total: int
    limit: int
    offset: int
