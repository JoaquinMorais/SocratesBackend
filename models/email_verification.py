from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


class EmailVerification(SQLModel, table=True):
    __tablename__ = "email_verifications"

    id_verification: int | None = Field(default=None, primary_key=True)
    id_user: int = Field(foreign_key="users.id_user", index=True)
    code_hash: str = Field(max_length=64)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))
    used: bool = False
    attempts: int = 0
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )