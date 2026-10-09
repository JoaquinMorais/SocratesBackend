from typing import Annotated

from fastapi import Depends, HTTPException, status

from models import Professor, Student
from utils.auth import user_dependency


async def get_professor(user: user_dependency) -> Professor:
    if not user.professor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Professors only")
    return user.professor


async def get_super_admin(
    professor: Annotated[Professor, Depends(get_professor)],
) -> Professor:
    if not professor.is_super_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admins only")
    return professor


async def get_student(user: user_dependency) -> Student:
    if not user.student:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Students only")
    return user.student


professor_dependency = Annotated[Professor, Depends(get_professor)]
super_admin_dependency = Annotated[Professor, Depends(get_super_admin)]
student_dependency = Annotated[Student, Depends(get_student)]