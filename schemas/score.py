from pydantic import ConfigDict, Field, field_validator
from sqlmodel import SQLModel


class SectionYearScorePublic(SQLModel):
    id_section_year_score: int
    id_score: int
    code: str
    name: str
    value: int


class SectionYearScoreList(SQLModel):
    items: list[SectionYearScorePublic]


class SectionYearScoreValue(SQLModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    value: int = Field(ge=1, le=100)


class SectionYearScoresUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    scores: list[SectionYearScoreValue] = Field(min_length=1)

    @field_validator("scores")
    @classmethod
    def unique_codes(cls, values):
        codes = [item.code for item in values]
        if len(codes) != len(set(codes)):
            raise ValueError("scores codes must be unique")
        return values
