from pydantic import ConfigDict
from sqlmodel import Field, SQLModel


class SectionYearCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    year: int = Field(ge=2000, le=2100)
    id_section: int = Field(gt=0)
    min_students: int = Field(ge=1, le=100)
    max_students: int = Field(ge=1, le=100)


class SectionYearUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    year: int | None = Field(default=None, ge=2000, le=2100)
    id_section: int | None = Field(default=None, gt=0)
    min_students: int | None = Field(default=None, ge=1, le=100)
    max_students: int | None = Field(default=None, ge=1, le=100)


class SectionYearPublic(SQLModel):
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    min_students: int
    max_students: int


class SectionYearList(SQLModel):
    items: list[SectionYearPublic]
    total: int
    limit: int
    offset: int