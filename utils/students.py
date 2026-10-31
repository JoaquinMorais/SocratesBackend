from fastapi import HTTPException, status
from sqlalchemy import case, false
from sqlmodel import col, delete, func, or_, select

from models import (
    EmailVerification,
    Project,
    RefreshToken,
    Section,
    SectionYear,
    Status,
    Student,
    StudentProject,
    StudentSectionYear,
    User,
)
from schemas.status import StatusPublic
from schemas.student import (
    StudentCreate,
    StudentGroupPublic,
    StudentListItem,
    StudentPublic,
    StudentUpdate,
)
from models.state import STUDENT_PROJECT_ORDER
from models.state.student_section_year import REGISTERED
from utils.statuses import get_status

# Membresías que impiden eliminar a un alumno (participación vigente o en espera).
# Los restos viejos (`abandoned`, `expelled`, `rejected`) se limpian con el alta.
STUDENT_DELETE_BLOCKED = frozenset({"active", "finished", "pending_approval"})

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

    # los cursos lectivos indicados para la cursada tienen que existir
    section_year_ids = {
        item.id_section_year for item in items if item.id_section_year is not None
    }
    section_years: dict[int, int] = {}  # id_section_year -> year
    if section_year_ids:
        rows = (
            await db.exec(
                select(SectionYear.id_section_year, SectionYear.year).where(
                    SectionYear.id_section_year.in_(section_year_ids)
                )
            )
        ).all()
        section_years = {id_sy: year for id_sy, year in rows}
        for row, item in enumerate(items, start=1):
            if item.id_section_year is not None and item.id_section_year not in section_years:
                errors.append(
                    {"row": row, "legajo": item.legajo, "detail": "Section year not found"}
                )

    if errors:
        errors.sort(key=lambda e: e["row"])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    registered_status = await get_status(
        db, "student_section_year", REGISTERED
    )
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
        if item.id_section_year is not None:
            db.add(
                StudentSectionYear(
                    id_student=user.id_user,
                    id_section_year=item.id_section_year,
                    year=section_years[item.id_section_year],
                    status=registered_status,
                    state=REGISTERED,
                )
            )
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


async def delete_student(db, id_student: int) -> None:
    """Elimina un alumno cargado por error.

    Solo si no tiene ninguna participación vigente ni en espera; los restos
    viejos (abandonos, expulsiones y rechazos) se borran con él. También borra
    sus cursadas (alumno + curso lectivo), sus sesiones (refresh tokens) y
    códigos OTP pendientes.
    """
    student = await db.get(Student, id_student)
    if not student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    blocking = (
        await db.exec(
            select(StudentProject.id_student)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_student == id_student,
                Status.code.in_(STUDENT_DELETE_BLOCKED),
            )
            .limit(1)
        )
    ).first()
    if blocking is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Student has an active, pending or finished membership and cannot be deleted",
        )

    await db.exec(delete(RefreshToken).where(RefreshToken.id_user == id_student))
    await db.exec(delete(EmailVerification).where(EmailVerification.id_user == id_student))
    await db.exec(delete(StudentSectionYear).where(StudentSectionYear.id_student == id_student))
    await db.exec(delete(StudentProject).where(StudentProject.id_student == id_student))
    user = student.user
    await db.delete(student)
    await db.delete(user)
    try:
        await db.commit()
    except IntegrityError:  # por si llegaron datos asociados a la vez
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Student is in use and cannot be deleted"
        )


def to_list_item(student: Student, groups: list[StudentGroupPublic]) -> StudentListItem:
    user = student.user
    return StudentListItem(
        id_student=student.id_student,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        email=Student.mail_from_legajo(user.legajo),
        enrollment_year=student.enrollment_year,
        groups=groups,
    )


async def _groups_by_student(
    db, student_ids: list[int], scope: list, statuses: list[str]
) -> dict[int, list[StudentGroupPublic]]:
    """Trae los grupos de todos los alumnos de la página en una sola consulta.

    Solo los grupos cuya membresía está en `statuses`, ordenados por la prioridad
    de `STUDENT_PROJECT_ORDER` y, dentro de cada estado, del curso más reciente
    al más viejo.
    """
    if not student_ids:
        return {}

    status_priority = case(
        {code: index for index, code in enumerate(STUDENT_PROJECT_ORDER)},
        value=Status.code,
        else_=len(STUDENT_PROJECT_ORDER),
    )
    rows = (
        await db.exec(
            select(
                StudentProject.id_student,
                Project.id_project,
                Project.name,
                Project.group_number,
                SectionYear.id_section_year,
                SectionYear.year,
                Section.id_section,
                Section.name,
                StudentProject.is_leader,
                Status.id_status,
                Status.ambito,
                Status.code,
                Status.name,
                Status.description,
                Status.is_final,
            )
            .join(Project, Project.id_project == StudentProject.id_project)
            .join(SectionYear, SectionYear.id_section_year == Project.id_section_year)
            .join(Section, Section.id_section == SectionYear.id_section)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_student.in_(student_ids),
                Status.ambito == "student_project",
                Status.code.in_(statuses),
                *scope,
            )
            .order_by(
                col(StudentProject.id_student),
                status_priority,
                col(SectionYear.year).desc(),
                col(Section.name),
                col(Project.group_number),
            )
        )
    ).all()

    groups: dict[int, list[StudentGroupPublic]] = {}
    for (
        id_student,
        id_project,
        project_name,
        group_number,
        id_section_year,
        year,
        id_section,
        section_name,
        is_leader,
        id_status,
        ambito,
        code,
        name,
        description,
        is_final,
    ) in rows:
        groups.setdefault(id_student, []).append(
            StudentGroupPublic(
                id_project=id_project,
                project_name=project_name,
                group_number=group_number,
                id_section_year=id_section_year,
                year=year,
                id_section=id_section,
                section_name=section_name,
                is_leader=is_leader,
                status=StatusPublic(
                    id_status=id_status,
                    ambito=ambito,
                    code=code,
                    name=name,
                    description=description,
                    is_final=is_final,
                ),
            )
        )
    return groups


async def list_students(
    db,
    access,
    *,
    statuses: list[str],
    id_section_year: int | None,
    year: int | None,
    id_section: int | None,
    q: str | None,
    limit: int,
    offset: int,
) -> tuple[list[StudentListItem], int]:
    if id_section_year is not None and not access.can_manage(id_section_year):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a professor of this section year or a super admin can do this",
        )

    # Condiciones sobre el curso lectivo: los filtros pedidos y, para un profesor
    # común, sus cursos lectivos. Si no hay ninguna, un super admin ve a todos.
    scope = []
    if id_section_year is not None:
        scope.append(Project.id_section_year == id_section_year)
    if year is not None:
        scope.append(SectionYear.year == year)
    if id_section is not None:
        scope.append(SectionYear.id_section == id_section)
    if not access.is_super_admin:
        if access.section_year_ids:
            scope.append(SectionYear.id_section_year.in_(access.section_year_ids))
        else:
            scope.append(false())  # profesor sin cursos asignados: no ve a nadie

    conditions = []
    if q:
        like = f"%{q.strip()}%"
        named_projects = (
            select(StudentProject.id_student)
            .join(Project, Project.id_project == StudentProject.id_project)
            .join(SectionYear, SectionYear.id_section_year == Project.id_section_year)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                *scope,
                col(Project.name).ilike(like),
                Status.ambito == "student_project",
                Status.code.in_(statuses),
            )
        )
        search = [
            col(User.first_name).ilike(like),
            col(User.last_name).ilike(like),
            Student.id_student.in_(named_projects),
        ]
        if q.strip().isdigit():
            search.append(User.legajo == int(q.strip()))
        conditions.append(or_(*search))

    if scope:
        # Solo alumnos con al menos un grupo, en los estados pedidos, dentro del alcance.
        enrolled = (
            select(StudentProject.id_student)
            .join(Project, Project.id_project == StudentProject.id_project)
            .join(SectionYear, SectionYear.id_section_year == Project.id_section_year)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                *scope,
                Status.ambito == "student_project",
                Status.code.in_(statuses),
            )
        )
        conditions.append(Student.id_student.in_(enrolled))

    on_user = User.id_user == Student.id_student
    total = (
        await db.exec(
            select(func.count())
            .select_from(Student)
            .join(User, on_user)
            .where(*conditions)
        )
    ).one()
    students = (
        await db.exec(
            select(Student)
            .join(User, on_user)
            .where(*conditions)
            .order_by(
                col(User.last_name), col(User.first_name), col(Student.id_student)
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    groups = await _groups_by_student(db, [s.id_student for s in students], scope, statuses)
    items = [to_list_item(s, groups.get(s.id_student, [])) for s in students]
    return items, total