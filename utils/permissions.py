from typing import Annotated

from fastapi import Depends, HTTPException, status

from models import Professor
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


professor_dependency = Annotated[Professor, Depends(get_professor)]
super_admin_dependency = Annotated[Professor, Depends(get_super_admin)]