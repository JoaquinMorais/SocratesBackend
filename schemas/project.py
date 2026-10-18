from typing import Literal

from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel

from schemas.status import StatusPublic

Privacy = Literal["public", "private", "protected"]


class ProjectCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    id_section_year: int = Field(gt=0)
    group_number: int | None = Field(default=None, gt=0, le=9999)


class ProjectBulkCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_section_year: int = Field(gt=0)
    quantity: int = Field(ge=1, le=50)


class ProjectUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    objective: str | None = None
    problem: str | None = None
    privacy: Privacy | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("name cannot be blank")
        return v

    @model_validator(mode="after")
    def privacy_cannot_be_null(self):
        # `privacy` es obligatoria en el modelo: un null explícito es inválido
        # (a diferencia de los campos de texto, donde null limpia el valor).
        if "privacy" in self.model_fields_set and self.privacy is None:
            raise ValueError("privacy cannot be null")
        return self


class ProjectPublic(SQLModel):
    id_project: int
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    group_number: int
    privacy: Privacy
    status: StatusPublic
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