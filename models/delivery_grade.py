from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, Relationship, SQLModel

from models.delivery import Delivery
from models.score import SectionYearScore


class DeliveryGrade(SQLModel, table=True):
    __tablename__ = "delivery_grades"
    __table_args__ = (
        CheckConstraint(
            "category IN ('follow_up', 'activity')",
            name="ck_delivery_grade_category",
        ),
    )

    id_delivery_grade: int | None = Field(default=None, primary_key=True)
    id_delivery: int = Field(
        foreign_key="deliveries.id_delivery", index=True, ondelete="CASCADE"
    )
    id_section_year_score: int = Field(
        foreign_key="section_year_scores.id_section_year_score", index=True
    )
    category: str = Field(max_length=30)
    graded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )

    delivery: Delivery = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    score: SectionYearScore = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
