from datetime import date as date_type
from datetime import time
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic import Field as PField
from sqlmodel import Field, SQLModel

Modality = Literal["in_person", "virtual"]


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _validate_url(value: str | None) -> str | None:
    value = _clean_text(value)
    if value is None:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("meeting_url must be an http(s) URL")
    return value


def _validate_weekdays(values: list[int]) -> list[int]:
    if any(weekday < 1 or weekday > 7 for weekday in values):
        raise ValueError("weekdays must be between 1 and 7 (ISO)")
    return sorted(set(values))


class CalendarClassCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    date: date_type
    start_time: time
    end_time: time
    modality: Modality = "in_person"
    title: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    meeting_url: str | None = Field(default=None, max_length=500)

    @field_validator("title", "location")
    @classmethod
    def normalize_text(cls, v: str | None) -> str | None:
        return _clean_text(v)

    @field_validator("meeting_url")
    @classmethod
    def normalize_url(cls, v: str | None) -> str | None:
        return _validate_url(v)

    @model_validator(mode="after")
    def valid_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class CalendarClassUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    date: date_type | None = None
    start_time: time | None = None
    end_time: time | None = None
    modality: Modality | None = None
    title: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    meeting_url: str | None = Field(default=None, max_length=500)

    @field_validator("title", "location")
    @classmethod
    def normalize_text(cls, v: str | None) -> str | None:
        return _clean_text(v)

    @field_validator("meeting_url")
    @classmethod
    def normalize_url(cls, v: str | None) -> str | None:
        return _validate_url(v)


class CalendarClassPublic(SQLModel):
    id_calendar_class: int
    id_calendar: int
    date: date_type
    weekday: int  # derivado de la fecha (ISO: 1 = lunes ... 7 = domingo)
    start_time: time
    end_time: time
    modality: Modality
    title: str | None = None
    location: str | None = None
    meeting_url: str | None = None


class CalendarClassBulkCreate(BaseModel):
    """Crea una clase por cada fecha que caiga en `weekdays` dentro de `from..to`."""

    model_config = ConfigDict(extra="forbid")

    weekdays: list[int] = PField(min_length=1)
    from_date: date_type
    to_date: date_type
    start_time: time
    end_time: time
    modality: Modality = "in_person"
    title: str | None = PField(default=None, max_length=100)
    location: str | None = PField(default=None, max_length=200)
    meeting_url: str | None = PField(default=None, max_length=500)

    @field_validator("title", "location")
    @classmethod
    def normalize_text(cls, v: str | None) -> str | None:
        return _clean_text(v)

    @field_validator("meeting_url")
    @classmethod
    def normalize_url(cls, v: str | None) -> str | None:
        return _validate_url(v)

    @field_validator("weekdays")
    @classmethod
    def normalize_weekdays(cls, v: list[int]) -> list[int]:
        return _validate_weekdays(v)

    @model_validator(mode="after")
    def valid_ranges(self):
        if self.from_date > self.to_date:
            raise ValueError("from must be before or equal to to")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class CalendarClassFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekdays: list[int] | None = None
    from_date: date_type | None = None
    to_date: date_type | None = None

    @field_validator("weekdays")
    @classmethod
    def normalize_weekdays(cls, v: list[int] | None) -> list[int] | None:
        return None if v is None else _validate_weekdays(v)

    @model_validator(mode="after")
    def has_criteria(self):
        if self.weekdays is None and self.from_date is None and self.to_date is None:
            raise ValueError("filter needs at least one criterion")
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.from_date > self.to_date
        ):
            raise ValueError("from must be before or equal to to")
        return self


class CalendarClassSelector(BaseModel):
    """Selección para operaciones en lote: ids o un filtro, nunca ambos."""

    model_config = ConfigDict(extra="forbid")

    ids: list[int] | None = PField(default=None, min_length=1)
    filter: CalendarClassFilter | None = None

    @model_validator(mode="after")
    def exactly_one_selector(self):
        if (self.ids is None) == (self.filter is None):
            raise ValueError("Send either ids or filter, not both")
        return self


class CalendarClassChanges(SQLModel):
    """Cambios de un lote (no se puede cambiar la fecha en lote)."""

    model_config = ConfigDict(extra="forbid")

    start_time: time | None = None
    end_time: time | None = None
    modality: Modality | None = None
    title: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    meeting_url: str | None = Field(default=None, max_length=500)

    @field_validator("title", "location")
    @classmethod
    def normalize_text(cls, v: str | None) -> str | None:
        return _clean_text(v)

    @field_validator("meeting_url")
    @classmethod
    def normalize_url(cls, v: str | None) -> str | None:
        return _validate_url(v)

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_fields_set:
            raise ValueError("No fields to update")
        return self


class CalendarClassBulkUpdate(CalendarClassSelector):
    changes: CalendarClassChanges
