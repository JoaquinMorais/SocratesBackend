from typing import Literal

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

Privacy = Literal["public", "private", "protected"]


class ProjectCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    id_section_year: int = Field(gt=0)
    group_number: int | None = Field(default=None, gt=0, le=9999)


class ProjectBulkCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_section_year: int = Field(gt=0)
    quantity: int = Field(ge=1, le=50)


class ProjectPublic(SQLModel):
    id_project: int
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    group_number: int
    privacy: Privacy
    restricted: bool = False  # true: el detalle está oculto para este usuario
    name: str | None = None
    description: str | None = None
    objective: str | None = None
    problem: str | None = None


class ProjectList(SQLModel):
    items: list[ProjectPublic]
    total: int
    limit: int
    offset: int