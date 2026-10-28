from datetime import date

from fastapi import HTTPException, status

MAX_RANGE_DAYS = 366


def validate_optional_range(
    from_date: date | None, to_date: date | None, *, max_days: int = MAX_RANGE_DAYS
) -> None:
    """Valida un rango opcional: ambos o ninguno, ordenado y acotado en días."""
    if (from_date is None) != (to_date is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Send both from and to, or neither",
        )
    if from_date is None:
        return
    if from_date > to_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "from must be before or equal to to",
        )
    if (to_date - from_date).days > max_days:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Date range is too long (max {max_days} days)",
        )
