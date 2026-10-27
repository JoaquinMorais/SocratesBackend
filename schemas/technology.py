from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel


class TechnologyCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be blank")
        return v


class TechnologyUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)

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
    def name_cannot_be_null(self):
        # `name` es obligatorio en el modelo: un null explícito es inválido
        # (a diferencia de `description`, donde null limpia el valor).
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class TechnologyPublic(SQLModel):
    id_technology: int
    name: str
    description: str | None = None


class TechnologyList(SQLModel):
    items: list[TechnologyPublic]
    total: int
    limit: int
    offset: int


class ProjectTechnologyCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_technology: int = Field(gt=0)


class ProjectTechnologyBulkCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_technologies: list[int] = Field(min_length=1, max_length=100)
