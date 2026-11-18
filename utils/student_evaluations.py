from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from models import (
    Student,
    StudentEvaluation,
    StudentGrade,
    StudentSectionYear,
    User,
)
from models.state.student_section_year import ATTENDING
from schemas.student_evaluation import (
    MyStudentEvaluationList,
    MyStudentEvaluationPublic,
    StudentEvaluationCreate,
    StudentEvaluationGradeSummaryPublic,
    StudentEvaluationList,
    StudentEvaluationListItemPublic,
    StudentEvaluationPublic,
    StudentEvaluationSummaryPublic,
    StudentEvaluationUpdate,
    StudentGradeBulkUpdate,
    StudentGradeCreate,
    StudentGradeList,
    StudentGradePublic,
    StudentGradeUpdate,
)
from utils.section_years import get_section_year


def _not_found_evaluation() -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, "Student evaluation not found"
    )


def _not_found_grade() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Student grade not found")


def _forbidden() -> HTTPException:
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can do this",
    )


def _duplicate_evaluation() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "A student evaluation with this name already exists in the section year",
    )


def _grade_conflict() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "This student already has a grade for the evaluation",
    )


def _require_staff(access, id_section_year: int) -> None:
    if not access.can_manage(id_section_year):
        _forbidden()


def _check_year(sy, evaluation_date) -> None:
    if evaluation_date.year != sy.year:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Evaluation date must be in the section year",
        )


async def get_evaluation(db, id_evaluation: int) -> StudentEvaluation:
    evaluation = await db.get(StudentEvaluation, id_evaluation)
    if evaluation is None:
        raise _not_found_evaluation()
    return evaluation


async def get_grade(db, id_grade: int) -> StudentGrade:
    grade = await db.get(StudentGrade, id_grade)
    if grade is None:
        raise _not_found_grade()
    return grade


def _evaluation_public(
    evaluation: StudentEvaluation,
) -> StudentEvaluationPublic:
    sy = evaluation.section_year
    section = sy.section
    return StudentEvaluationPublic(
        id_student_evaluation=evaluation.id_student_evaluation,
        id_section_year=sy.id_section_year,
        year=sy.year,
        id_section=section.id_section,
        section_name=section.name,
        name=evaluation.name,
        description=evaluation.description,
        date=evaluation.date,
        created_at=evaluation.created_at,
    )


def _summary(grades: list[int]) -> StudentEvaluationSummaryPublic:
    loaded = [grade for grade in grades if grade > 0]
    return StudentEvaluationSummaryPublic(
        evaluations_total=len(grades),
        graded_grades_total=len(loaded),
        average_grade=(
            round(sum(loaded) / len(loaded), 2) if loaded else None
        ),
    )


async def _grades_for_evaluation(
    db, id_evaluation: int
) -> list[StudentGrade]:
    return list(
        (
            await db.exec(
                select(StudentGrade)
                .where(StudentGrade.id_student_evaluation == id_evaluation)
                .order_by(StudentGrade.id_student_grade)
            )
        ).all()
    )


async def list_evaluations_for_section_year(
    db, access, id_section_year: int
) -> StudentEvaluationList:
    await get_section_year(db, id_section_year)
    _require_staff(access, id_section_year)
    evaluations = (
        await db.exec(
            select(StudentEvaluation)
            .where(StudentEvaluation.id_section_year == id_section_year)
            .order_by(
                col(StudentEvaluation.date).desc(),
                col(StudentEvaluation.id_student_evaluation),
            )
        )
    ).all()
    grades = (
        await db.exec(
            select(
                StudentGrade.id_student_evaluation,
                StudentGrade.grade,
            ).where(
                StudentGrade.id_student_evaluation.in_(
                    [e.id_student_evaluation for e in evaluations]
                )
            )
        )
    ).all()
    grades_by_evaluation: dict[int, list[int]] = {}
    for id_evaluation, grade in grades:
        grades_by_evaluation.setdefault(id_evaluation, []).append(grade)

    items = []
    for evaluation in evaluations:
        summary = _summary(grades_by_evaluation.get(evaluation.id_student_evaluation, []))
        items.append(
            StudentEvaluationListItemPublic(
                **_evaluation_public(evaluation).model_dump(),
                grades_total=summary.evaluations_total,
                graded_grades_total=summary.graded_grades_total,
                average_grade=summary.average_grade,
            )
        )
    return StudentEvaluationList(items=items, total=len(items))


async def get_evaluation_public(
    db, access, id_evaluation: int
) -> StudentEvaluationListItemPublic:
    evaluation = await get_evaluation(db, id_evaluation)
    _require_staff(access, evaluation.id_section_year)
    grades = await _grades_for_evaluation(db, id_evaluation)
    stats = _summary([grade.grade for grade in grades])
    return StudentEvaluationListItemPublic(
        **_evaluation_public(evaluation).model_dump(),
        grades_total=stats.evaluations_total,
        graded_grades_total=stats.graded_grades_total,
        average_grade=stats.average_grade,
    )


async def create_evaluation(
    db, access, id_section_year: int, data: StudentEvaluationCreate
) -> StudentEvaluationPublic:
    sy = await get_section_year(db, id_section_year)
    _require_staff(access, id_section_year)
    _check_year(sy, data.date)
    taken = (
        await db.exec(
            select(StudentEvaluation.id_student_evaluation).where(
                StudentEvaluation.id_section_year == id_section_year,
                func.lower(StudentEvaluation.name) == data.name.lower(),
            )
        )
    ).first()
    if taken is not None:
        raise _duplicate_evaluation()

    evaluation = StudentEvaluation(
        id_section_year=id_section_year,
        name=data.name,
        description=data.description,
        date=data.date,
        section_year=sy,
    )
    db.add(evaluation)
    try:
        await db.flush()
        cursadas = (
            await db.exec(
                select(StudentSectionYear).where(
                    StudentSectionYear.id_section_year == id_section_year,
                    StudentSectionYear.state == ATTENDING,
                )
            )
        ).all()
        for cursada in cursadas:
            db.add(
                StudentGrade(
                    id_student_evaluation=evaluation.id_student_evaluation,
                    id_student_section_year=cursada.id_student_section_year,
                    grade=0,
                )
            )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate_evaluation()
    return _evaluation_public(evaluation)


async def update_evaluation(
    db,
    access,
    id_evaluation: int,
    data: StudentEvaluationUpdate,
) -> StudentEvaluationPublic:
    evaluation = await get_evaluation(db, id_evaluation)
    _require_staff(access, evaluation.id_section_year)
    changes = data.model_fields_set
    if not changes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update"
        )
    if "name" in changes:
        if data.name is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "name cannot be null"
            )
        if data.name.lower() != evaluation.name.lower():
            taken = (
                await db.exec(
                    select(StudentEvaluation.id_student_evaluation).where(
                        StudentEvaluation.id_section_year
                        == evaluation.id_section_year,
                        func.lower(StudentEvaluation.name) == data.name.lower(),
                        StudentEvaluation.id_student_evaluation != id_evaluation,
                    )
                )
            ).first()
            if taken is not None:
                raise _duplicate_evaluation()
    if "date" in changes:
        if data.date is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "date cannot be null"
            )
        _check_year(evaluation.section_year, data.date)
    for field in changes:
        setattr(evaluation, field, getattr(data, field))
    db.add(evaluation)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate_evaluation()
    return _evaluation_public(evaluation)


async def delete_evaluation(db, access, id_evaluation: int) -> None:
    evaluation = await get_evaluation(db, id_evaluation)
    _require_staff(access, evaluation.id_section_year)
    await db.delete(evaluation)
    await db.commit()


async def list_grades(
    db, access, id_evaluation: int
) -> StudentGradeList:
    evaluation = await get_evaluation(db, id_evaluation)
    _require_staff(access, evaluation.id_section_year)
    rows = (
        await db.exec(
            select(StudentGrade, Student, User)
            .join(
                StudentSectionYear,
                StudentSectionYear.id_student_section_year
                == StudentGrade.id_student_section_year,
            )
            .join(Student, Student.id_student == StudentSectionYear.id_student)
            .join(User, User.id_user == Student.id_student)
            .where(StudentGrade.id_student_evaluation == id_evaluation)
            .order_by(col(User.last_name), col(User.first_name), col(Student.id_student))
        )
    ).all()
    return StudentGradeList(
        items=[
            StudentGradePublic(
                id_student_grade=grade.id_student_grade,
                id_student_evaluation=grade.id_student_evaluation,
                id_student_section_year=grade.id_student_section_year,
                id_student=student.id_student,
                first_name=user.first_name,
                last_name=user.last_name,
                legajo=user.legajo,
                grade=grade.grade,
                updated_at=grade.updated_at,
            )
            for grade, student, user in rows
        ]
    )


def _grade_public_from_row(
    grade: StudentGrade, student: Student, user: User
) -> StudentGradePublic:
    return StudentGradePublic(
        id_student_grade=grade.id_student_grade,
        id_student_evaluation=grade.id_student_evaluation,
        id_student_section_year=grade.id_student_section_year,
        id_student=student.id_student,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        grade=grade.grade,
        updated_at=grade.updated_at,
    )


async def _grade_with_student(db, id_grade: int):
    return (
        await db.exec(
            select(StudentGrade, Student, User)
            .join(
                StudentSectionYear,
                StudentSectionYear.id_student_section_year
                == StudentGrade.id_student_section_year,
            )
            .join(Student, Student.id_student == StudentSectionYear.id_student)
            .join(User, User.id_user == Student.id_student)
            .where(StudentGrade.id_student_grade == id_grade)
        )
    ).first()


async def create_grade(
    db, access, id_evaluation: int, data: StudentGradeCreate
) -> StudentGradePublic:
    evaluation = await get_evaluation(db, id_evaluation)
    _require_staff(access, evaluation.id_section_year)
    row = (
        await db.exec(
            select(StudentSectionYear, Student, User)
            .join(Student, Student.id_student == StudentSectionYear.id_student)
            .join(User, User.id_user == Student.id_student)
            .where(
                StudentSectionYear.id_student_section_year
                == data.id_student_section_year
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student cursada not found")
    cursada, student, user = row
    if cursada.id_section_year != evaluation.id_section_year:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Student cursada does not belong to the evaluation section year",
        )
    if cursada.state != ATTENDING:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Student is not attending this section year",
        )
    existing = (
        await db.exec(
            select(StudentGrade).where(
                StudentGrade.id_student_evaluation == id_evaluation,
                StudentGrade.id_student_section_year
                == data.id_student_section_year,
            )
        )
    ).first()
    if existing is not None:
        raise _grade_conflict()
    grade = StudentGrade(
        id_student_evaluation=id_evaluation,
        id_student_section_year=data.id_student_section_year,
        grade=data.grade,
        evaluation=evaluation,
        student_section_year=cursada,
    )
    db.add(grade)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _grade_conflict()
    return _grade_public_from_row(grade, student, user)


async def update_grade(
    db, access, id_grade: int, data: StudentGradeUpdate
) -> StudentGradePublic:
    row = await _grade_with_student(db, id_grade)
    if row is None:
        raise _not_found_grade()
    grade, student, user = row
    _require_staff(access, grade.evaluation.id_section_year)
    grade.grade = data.grade
    grade.updated_at = datetime.now(timezone.utc)
    db.add(grade)
    await db.commit()
    return _grade_public_from_row(grade, student, user)


async def delete_grade(db, access, id_grade: int) -> None:
    grade = await get_grade(db, id_grade)
    _require_staff(access, grade.evaluation.id_section_year)
    await db.delete(grade)
    await db.commit()


async def bulk_update_grades(
    db, access, id_evaluation: int, data: StudentGradeBulkUpdate
) -> StudentGradeList:
    evaluation = await get_evaluation(db, id_evaluation)
    _require_staff(access, evaluation.id_section_year)

    seen: set[int] = set()
    errors = []
    for row, item in enumerate(data.grades, start=1):
        if item.id_student_section_year in seen:
            errors.append(
                {
                    "row": row,
                    "id_student_section_year": item.id_student_section_year,
                    "detail": "Duplicated in the request",
                }
            )
        seen.add(item.id_student_section_year)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    rows = (
        await db.exec(
            select(StudentGrade, StudentSectionYear)
            .join(
                StudentSectionYear,
                StudentSectionYear.id_student_section_year
                == StudentGrade.id_student_section_year,
            )
            .where(
                StudentGrade.id_student_evaluation == id_evaluation,
                StudentGrade.id_student_section_year.in_(seen),
            )
        )
    ).all()
    existing = {
        grade.id_student_section_year: (grade, cursada)
        for grade, cursada in rows
    }
    for row, item in enumerate(data.grades, start=1):
        if item.id_student_section_year not in existing:
            errors.append(
                {
                    "row": row,
                    "id_student_section_year": item.id_student_section_year,
                    "detail": "Student grade not found for this evaluation",
                }
            )
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    updated = []
    for item in data.grades:
        grade, cursada = existing[item.id_student_section_year]
        grade.grade = item.grade
        grade.updated_at = datetime.now(timezone.utc)
        db.add(grade)
        updated.append((grade, cursada))
    await db.commit()

    result = []
    for grade, cursada in updated:
        student = await db.get(Student, cursada.id_student)
        user = await db.get(User, cursada.id_student)
        result.append(_grade_public_from_row(grade, student, user))
    return StudentGradeList(items=result)


async def backfill_grades_for_cursada(
    db, id_student: int, id_section_year: int
) -> None:
    """Crea notas 0 para evaluaciones existentes al pasar a `attending`."""
    cursada = (
        await db.exec(
            select(StudentSectionYear).where(
                StudentSectionYear.id_student == id_student,
                StudentSectionYear.id_section_year == id_section_year,
                StudentSectionYear.state == ATTENDING,
            )
        )
    ).first()
    if cursada is None:
        return
    evaluation_ids = (
        await db.exec(
            select(StudentEvaluation.id_student_evaluation).where(
                StudentEvaluation.id_section_year == id_section_year
            )
        )
    ).all()
    if not evaluation_ids:
        return
    existing = set(
        (
            await db.exec(
                select(StudentGrade.id_student_evaluation).where(
                    StudentGrade.id_student_section_year
                    == cursada.id_student_section_year,
                    StudentGrade.id_student_evaluation.in_(evaluation_ids),
                )
            )
        ).all()
    )
    for id_evaluation in evaluation_ids:
        if id_evaluation not in existing:
            db.add(
                StudentGrade(
                    id_student_evaluation=id_evaluation,
                    id_student_section_year=cursada.id_student_section_year,
                    grade=0,
                )
            )
    await db.flush()


async def list_my_evaluations(
    db, id_student: int
) -> MyStudentEvaluationList:
    rows = (
        await db.exec(
            select(StudentGrade, StudentEvaluation)
            .join(
                StudentSectionYear,
                StudentSectionYear.id_student_section_year
                == StudentGrade.id_student_section_year,
            )
            .join(
                StudentEvaluation,
                StudentEvaluation.id_student_evaluation
                == StudentGrade.id_student_evaluation,
            )
            .where(StudentSectionYear.id_student == id_student)
            .order_by(
                col(StudentEvaluation.date).desc(),
                col(StudentEvaluation.id_student_evaluation).desc(),
            )
        )
    ).all()
    items = []
    for grade, evaluation in rows:
        public = _evaluation_public(evaluation)
        items.append(
            MyStudentEvaluationPublic(
                **public.model_dump(),
                grade=grade.grade,
            )
        )
    return MyStudentEvaluationList(items=items)


async def grades_for_cursadas(
    db, cursada_ids: list[int]
) -> dict[int, list[StudentEvaluationGradeSummaryPublic]]:
    if not cursada_ids:
        return {}
    rows = (
        await db.exec(
            select(StudentGrade, StudentEvaluation)
            .join(
                StudentEvaluation,
                StudentEvaluation.id_student_evaluation
                == StudentGrade.id_student_evaluation,
            )
            .where(StudentGrade.id_student_section_year.in_(cursada_ids))
            .order_by(
                col(StudentEvaluation.date).desc(),
                col(StudentEvaluation.id_student_evaluation).desc(),
            )
        )
    ).all()
    result: dict[int, list[StudentEvaluationGradeSummaryPublic]] = {}
    for grade, evaluation in rows:
        result.setdefault(grade.id_student_section_year, []).append(
            StudentEvaluationGradeSummaryPublic(
                id_student_evaluation=evaluation.id_student_evaluation,
                name=evaluation.name,
                date=evaluation.date,
                grade=grade.grade,
            )
        )
    return result


def evaluation_average(grades: list[StudentEvaluationGradeSummaryPublic]) -> float | None:
    loaded = [grade.grade for grade in grades if grade.grade > 0]
    return round(sum(loaded) / len(loaded), 2) if loaded else None


def evaluation_summary(
    grades_by_cursada: dict[int, list[StudentEvaluationGradeSummaryPublic]],
) -> StudentEvaluationSummaryPublic:
    all_grades = [
        grade.grade
        for grades in grades_by_cursada.values()
        for grade in grades
    ]
    loaded = [grade for grade in all_grades if grade > 0]
    return StudentEvaluationSummaryPublic(
        evaluations_total=len(all_grades),
        graded_grades_total=len(loaded),
        average_grade=round(sum(loaded) / len(loaded), 2) if loaded else None,
    )
