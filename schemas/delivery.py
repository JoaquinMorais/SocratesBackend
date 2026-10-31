from datetime import date as date_type
from datetime import datetime, time
from urllib.parse import urlsplit

from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel

from schemas.activity import ActivityPublic


def _validate_link(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("link must be an http(s) URL")
    return value


class DeliveryUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    link: str | None = Field(default=None, max_length=1000)
    activity_grade: int | None = Field(default=None, ge=1, le=100)
    development_grade: int | None = Field(default=None, ge=1, le=100)

    @field_validator("link")
    @classmethod
    def normalize_link(cls, value: str | None) -> str | None:
        return _validate_link(value)


class DeliveryRepairCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_activity: int = Field(gt=0)
    link: str | None = Field(default=None, max_length=1000)
    activity_grade: int | None = Field(default=None, ge=1, le=100)
    development_grade: int | None = Field(default=None, ge=1, le=100)

    @field_validator("link")
    @classmethod
    def normalize_link(cls, value: str | None) -> str | None:
        return _validate_link(value)

    @model_validator(mode="after")
    def at_least_one_value(self):
        if self.link is None and self.activity_grade is None and self.development_grade is None:
            raise ValueError("link or at least one grade is required")
        return self


class DeliveryProjectSummary(SQLModel):
    id_project: int
    group_number: int
    name: str | None = None


class DeliveryPublic(SQLModel):
    id_delivery: int
    id_project: int
    id_activity: int
    id_section_year: int
    activity: ActivityPublic
    project: DeliveryProjectSummary
    link: str | None = None
    activity_grade: int | None = None
    development_grade: int | None = None
    submitted_at: datetime | None = None
    updated_at: datetime | None = None


class DeliveryList(SQLModel):
    items: list[DeliveryPublic]
    total: int
    limit: int
    offset: int
