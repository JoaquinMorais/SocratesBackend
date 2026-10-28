from datetime import date as date_type
from datetime import time

from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel


class ActivityCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    due_date: date_type
    due_time: time | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title cannot be blank")
        return v


class ActivityUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    due_date: date_type | None = None
    due_time: time | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("title cannot be blank")
        return v

    @model_validator(mode="after")
    def title_cannot_be_null(self):
        # `title` es obligatorio: un null explícito es inválido (a diferencia de
        # `description` y `due_time`, que se limpian con null).
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        return self


class ActivityPublic(SQLModel):
    id_activity: int
    id_calendar: int
    id_section_year: int
    title: str
    description: str | None = None
    due_date: date_type
    due_time: time | None = None


class ActivityList(SQLModel):
    items: list[ActivityPublic]
    total: int
    limit: int
    offset: int
