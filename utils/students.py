from fastapi import HTTPException, status
from sqlmodel import select

from models import Student, User
from schemas.student import StudentCreate, StudentPublic, StudentUpdate

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


async def update_student(db, id_student: int, data: StudentUpdate) -> StudentPublic:
    student = await db.get(Student, id_student)
    if not student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    user = student.user
    new_legajo = changes.get("legajo")
    if new_legajo is not None and new_legajo != user.legajo:
        taken = (
            await db.exec(
                select(Student.id_student)
                .join(User, User.id_user == Student.id_student)
                .where(User.legajo == new_legajo, Student.id_student != id_student)
            )
        ).first()
        if taken is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A student with this legajo already exists"
            )

    for field in ("first_name", "last_name", "birth_date", "legajo"):
        if field in changes:
            setattr(user, field, changes[field])
    if "enrollment_year" in changes:
        student.enrollment_year = changes["enrollment_year"]

    db.add(user)
    db.add(student)
    await db.commit()

    return StudentPublic(
        id_student=id_student,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        email=Student.mail_from_legajo(user.legajo),
        enrollment_year=student.enrollment_year,
    )