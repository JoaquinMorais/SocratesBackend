from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from models import Professor, User
from schemas.professor import ProfessorCreate, ProfessorPublic


async def create_professor(db, item: ProfessorCreate) -> ProfessorPublic:
    taken = (
        await db.exec(select(Professor.id_professor).where(Professor.mail == item.mail))
    ).first()
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A professor with this mail already exists")

    user = User(
        first_name=item.first_name,
        last_name=item.last_name,
        legajo=item.legajo,
        birth_date=item.birth_date,
    )
    db.add(user)
    await db.flush()  # obtiene id_user
    db.add(
        Professor(
            id_professor=user.id_user,
            mail=item.mail,
            is_super_admin=item.is_super_admin,
        )
    )

    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas con el mismo mail
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A professor with this mail already exists")

    return ProfessorPublic(
        id_professor=user.id_user,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        email=item.mail,
        is_super_admin=item.is_super_admin,
    )