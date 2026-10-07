from fastapi import HTTPException, status
from sqlmodel import select

from models import Student, User
from schemas.student import StudentCreate, StudentPublic


async def create_students(db, items: list[StudentCreate]) -> list[StudentPublic]:
    """Todo o nada: si alguna fila falla, no se crea ninguna."""
    errors: list[dict] = []
    first_row: dict[int, int] = {}  # legajo -> primera fila donde aparece

    for row, item in enumerate(items, start=1):
        if item.legajo in first_row:
            errors.append(
                {
                    "row": row,
                    "legajo": item.legajo,
                    "detail": f"Duplicated in the request (first seen in row {first_row[item.legajo]})",
                }
            )
        else:
            first_row[item.legajo] = row

    # el legajo no puede repetirse entre alumnos (el mail se calcula con él)
    existing = (
        await db.exec(
            select(User.legajo)
            .join(Student, Student.id_student == User.id_user)
            .where(User.legajo.in_(list(first_row)))
        )
    ).all()
    for legajo in existing:
        errors.append(
            {"row": first_row[legajo], "legajo": legajo, "detail": "A student with this legajo already exists"}
        )

    if errors:
        errors.sort(key=lambda e: e["row"])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    created: list[StudentPublic] = []
    for item in items:
        user = User(
            first_name=item.first_name,
            last_name=item.last_name,
            legajo=item.legajo,
            birth_date=item.birth_date,
        )
        db.add(user)
        await db.flush()  # obtiene id_user
        db.add(Student(id_student=user.id_user, enrollment_year=item.enrollment_year))
        created.append(
            StudentPublic(
                id_student=user.id_user,
                first_name=user.first_name,
                last_name=user.last_name,
                legajo=user.legajo,
                email=Student.mail_from_legajo(user.legajo),
                enrollment_year=item.enrollment_year,
            )
        )

    await db.commit()
    return created