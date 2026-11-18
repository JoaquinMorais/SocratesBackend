from typing import Annotated

from fastapi import APIRouter, status

from config.database import db_dependency
from schemas.student_evaluation import (
    MyStudentEvaluationList,
    StudentEvaluationCreate,
    StudentEvaluationList,
    StudentEvaluationListItemPublic,
    StudentEvaluationPublic,
    StudentEvaluationUpdate,
    StudentGradeBulkUpdate,
    StudentGradeCreate,
    StudentGradeList,
    StudentGradePublic,
    StudentGradeUpdate,
)
from utils.auth import user_dependency
from utils.permissions import professor_dependency, student_dependency
from utils.projects import build_access
from utils.student_evaluations import (
    bulk_update_grades,
    create_evaluation,
    create_grade,
    delete_evaluation,
    delete_grade,
    get_evaluation_public,
    list_evaluations_for_section_year,
    list_grades,
    list_my_evaluations,
    update_evaluation,
    update_grade,
)

student_evaluations_router = APIRouter(tags=["student-evaluations"])

_AUTH_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}
_STAFF_ERRORS = {
    **_AUTH_ERRORS,
    403: {"description": "El usuario no es profesor del curso ni super admin"},
}
_EVALUATION_ERRORS = {
    **_STAFF_ERRORS,
    404: {"description": "No existe la evaluación"},
}
_GRADE_ERRORS = {
    **_STAFF_ERRORS,
    404: {"description": "No existe la nota o la evaluación"},
    422: {"description": "Datos inválidos o alumno fuera de la cursada"},
}


@student_evaluations_router.get(
    "/section-years/{id_section_year}/student-evaluations",
    response_model=StudentEvaluationList,
    summary="Listar las evaluaciones de un curso lectivo",
    responses=_STAFF_ERRORS,
)
async def list_student_evaluations_route(
    id_section_year: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Lista las evaluaciones/parciales del curso, con cantidad de notas cargadas y
    promedio. **Solo profesor del curso o super admin.**
    """
    access = await build_access(db, user)
    return await list_evaluations_for_section_year(
        db, access, id_section_year
    )


@student_evaluations_router.post(
    "/section-years/{id_section_year}/student-evaluations",
    response_model=StudentEvaluationPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una evaluación de alumnos",
    responses={
        **_STAFF_ERRORS,
        404: {"description": "No existe el curso lectivo"},
        409: {"description": "Ya existe una evaluación con ese nombre en el curso"},
        422: {
            "description": (
                "Nombre vacío, fecha fuera del año del curso o campos desconocidos"
            )
        },
    },
)
async def create_student_evaluation_route(
    id_section_year: int,
    data: StudentEvaluationCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Crea una evaluación/parcial y genera una nota `0` para cada alumno con
    cursada `attending` en ese curso. **Solo profesor del curso o super admin.**
    """
    access = await build_access(db, user)
    return await create_evaluation(db, access, id_section_year, data)


@student_evaluations_router.get(
    "/student-evaluations/{id_student_evaluation}",
    response_model=StudentEvaluationListItemPublic,
    summary="Consultar una evaluación de alumnos",
    responses=_EVALUATION_ERRORS,
)
async def get_student_evaluation_route(
    id_student_evaluation: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Devuelve una evaluación y sus estadísticas de notas. **Solo profesor del
    curso o super admin.**
    """
    access = await build_access(db, user)
    return await get_evaluation_public(db, access, id_student_evaluation)


@student_evaluations_router.patch(
    "/student-evaluations/{id_student_evaluation}",
    response_model=StudentEvaluationPublic,
    summary="Modificar una evaluación de alumnos",
    responses={
        **_EVALUATION_ERRORS,
        409: {"description": "Ya existe otra evaluación con ese nombre en el curso"},
        422: {"description": "Body vacío, fecha inválida o campos desconocidos"},
    },
)
async def update_student_evaluation_route(
    id_student_evaluation: int,
    data: StudentEvaluationUpdate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Modifica nombre, descripción o fecha de una evaluación. **Solo profesor del
    curso o super admin.** No se puede cambiar el curso lectivo.
    """
    access = await build_access(db, user)
    return await update_evaluation(db, access, id_student_evaluation, data)


@student_evaluations_router.delete(
    "/student-evaluations/{id_student_evaluation}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una evaluación de alumnos",
    responses=_EVALUATION_ERRORS,
)
async def delete_student_evaluation_route(
    id_student_evaluation: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """Elimina una evaluación y sus notas. **Solo profesor del curso o super admin.**"""
    access = await build_access(db, user)
    await delete_evaluation(db, access, id_student_evaluation)


@student_evaluations_router.get(
    "/student-evaluations/{id_student_evaluation}/grades",
    response_model=StudentGradeList,
    summary="Listar las notas de una evaluación",
    responses=_EVALUATION_ERRORS,
)
async def list_student_grades_route(
    id_student_evaluation: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Lista las notas de todos los alumnos de una evaluación. **Solo profesor del
    curso o super admin.**
    """
    access = await build_access(db, user)
    return await list_grades(db, access, id_student_evaluation)


@student_evaluations_router.post(
    "/student-evaluations/{id_student_evaluation}/grades",
    response_model=StudentGradePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una nota de evaluación",
    responses={
        **_GRADE_ERRORS,
        409: {"description": "El alumno ya tiene una nota para esta evaluación"},
    },
)
async def create_student_grade_route(
    id_student_evaluation: int,
    data: StudentGradeCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Crea manualmente la nota de una cursada para una evaluación. La cursada debe
    ser `attending` y pertenecer al curso. **Solo profesor del curso o super admin.**
    """
    access = await build_access(db, user)
    return await create_grade(db, access, id_student_evaluation, data)


@student_evaluations_router.patch(
    "/student-evaluations/{id_student_evaluation}/grades/bulk",
    response_model=StudentGradeList,
    summary="Actualizar varias notas de una evaluación",
    responses={
        **_EVALUATION_ERRORS,
        422: {"description": "Lista inválida, duplicados, nota fuera de 1-10 o alumno ajeno"},
    },
)
async def bulk_update_student_grades_route(
    id_student_evaluation: int,
    data: StudentGradeBulkUpdate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Actualiza notas de varios alumnos en una sola operación, todo o nada.
    **Solo profesor del curso o super admin.**
    """
    access = await build_access(db, user)
    return await bulk_update_grades(db, access, id_student_evaluation, data)


@student_evaluations_router.patch(
    "/student-grades/{id_student_grade}",
    response_model=StudentGradePublic,
    summary="Modificar la nota de un alumno",
    responses=_GRADE_ERRORS,
)
async def update_student_grade_route(
    id_student_grade: int,
    data: StudentGradeUpdate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """Modifica una nota entre 1 y 10. **Solo profesor del curso o super admin.**"""
    access = await build_access(db, user)
    return await update_grade(db, access, id_student_grade, data)


@student_evaluations_router.delete(
    "/student-grades/{id_student_grade}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar la nota de un alumno",
    responses=_GRADE_ERRORS,
)
async def delete_student_grade_route(
    id_student_grade: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """Elimina una nota. **Solo profesor del curso o super admin.**"""
    access = await build_access(db, user)
    await delete_grade(db, access, id_student_grade)


@student_evaluations_router.get(
    "/me/student-evaluations",
    response_model=MyStudentEvaluationList,
    summary="Consultar mis notas de evaluaciones",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es alumno"},
    },
)
async def get_my_student_evaluations_route(
    db: db_dependency,
    student: student_dependency,
):
    """
    Devuelve las evaluaciones de las cursadas del alumno logueado y **solo su
    propia nota**. **Solo alumnos.**
    """
    return await list_my_evaluations(db, student.id_student)
