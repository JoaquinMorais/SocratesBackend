from pydantic import BaseModel, ConfigDict, Field as PField, model_validator
from sqlmodel import SQLModel

from schemas.activity import ActivityCreate
from schemas.calendar_class import CalendarClassCreate

MAX_BULK_CLASSES = 1000
MAX_BULK_ACTIVITIES = 200


class CalendarBulkLoad(BaseModel):
    """Carga inicial del calendario de un curso lectivo.

    Es un append: agrega las filas al calendario existente, sin borrar nada.
    """

    model_config = ConfigDict(extra="forbid")

    classes: list[CalendarClassCreate] = PField(
        default_factory=list, max_length=MAX_BULK_CLASSES
    )
    activities: list[ActivityCreate] = PField(
        default_factory=list, max_length=MAX_BULK_ACTIVITIES
    )

    @model_validator(mode="after")
    def at_least_one_row(self):
        if not self.classes and not self.activities:
            raise ValueError("Send at least one class or activity")
        return self


class CalendarBulkLoadReport(SQLModel):
    dry_run: bool
    classes_created: int
    activities_created: int
