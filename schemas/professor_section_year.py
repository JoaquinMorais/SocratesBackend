from pydantic import ConfigDict
from sqlmodel import Field, SQLModel


class ProfessorSectionYearCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    id_professor: int = Field(gt=0)
    id_section_year: int = Field(gt=0)


class ProfessorSectionYearUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_professor: int | None = Field(default=None, gt=0)
    id_section_year: int | None = Field(default=None, gt=0)


class ProfessorSectionYearPublic(SQLModel):
    id_professor_section_year: int
    id_professor: int
    professor_first_name: str
    professor_last_name: str
    id_section_year: int
    year: int
    id_section: int
    section_name: str


class ProfessorSectionYearList(SQLModel):
    items: list[ProfessorSectionYearPublic]
    total: int
    limit: int
    offset: int