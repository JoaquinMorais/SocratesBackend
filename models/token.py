from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id_refresh_token: int | None = Field(default=None, primary_key=True)
    id_user: int = Field(foreign_key="users.id_user", index=True)
    token_hash: str = Field(unique=True, index=True, max_length=64)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )