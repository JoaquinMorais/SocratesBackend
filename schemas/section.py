from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel


class SectionCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    name: str = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("name cannot be blank")
        return v


class SectionUpdate(SectionCreate):
    pass


class SectionPublic(SQLModel):
    id_section: int
    name: str


class SectionList(SQLModel):
    items: list[SectionPublic]
    total: int
    limit: int
    offset: int