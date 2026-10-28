from datetime import datetime

from sqlmodel import SQLModel


class ImagePublic(SQLModel):
    """Imagen guardada (siempre WebP); `url` apunta al archivo servido."""

    id_image: int
    url: str
    original_name: str | None = None
    content_type: str
    size_bytes: int
    created_at: datetime
