from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


class Image(SQLModel, table=True):
    __tablename__ = "images"

    id_image: int | None = Field(default=None, primary_key=True)
    # Clave dentro del almacenamiento (local por ahora): `images/<uuid>.webp`.
    key: str = Field(unique=True, index=True, max_length=255)
    # Nombre original del archivo subido, saneado (solo informativo).
    original_name: str | None = Field(default=None, max_length=255)
    content_type: str = Field(default="image/webp", max_length=100)
    size_bytes: int
    # Sha256 del archivo convertido; permite detectar el mismo contenido.
    checksum: str = Field(index=True, max_length=64)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
