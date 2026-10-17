from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select

from models import EmailVerification, Professor, RefreshToken, User
from schemas.professor import ProfessorCreate, ProfessorPublic, ProfessorUpdate


async def _professor_legajo_taken(db, legajo: int, exclude_id: int | None = None) -> bool:
    stmt = select(Professor.id_professor).join(
        User, User.id_user == Professor.id_professor
    ).where(User.legajo == legajo)
    if exclude_id is not None:
        stmt = stmt.where(Professor.id_professor != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def create_professor(db, item: ProfessorCreate) -> ProfessorPublic:
    taken = (
        await db.exec(select(Professor.id_professor).where(Professor.mail == item.mail))
    ).first()
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A professor with this mail already exists")

    if await _professor_legajo_taken(db, item.legajo):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A professor with this legajo already exists"
        )

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


async def update_professor(
    db, actor: Professor, id_professor: int, data: ProfessorUpdate
) -> ProfessorPublic:
    professor = await db.get(Professor, id_professor)
    if not professor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Professor not found")

    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    if changes.get("is_super_admin") is False and id_professor == actor.id_professor:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You cannot remove your own super admin status"
        )

    user = professor.user
    mail_changed = "mail" in changes and changes["mail"] != professor.mail
    if mail_changed:
        taken = (
            await db.exec(select(Professor.id_professor).where(Professor.mail == changes["mail"]))
        ).first()
        if taken is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A professor with this mail already exists"
            )

    new_legajo = changes.get("legajo")
    if new_legajo is not None and new_legajo != user.legajo:
        if await _professor_legajo_taken(db, new_legajo, exclude_id=id_professor):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A professor with this legajo already exists"
            )

    for field in ("first_name", "last_name", "birth_date", "legajo"):
        if field in changes:
            setattr(user, field, changes[field])
    if "mail" in changes:
        professor.mail = changes["mail"]
    if "is_super_admin" in changes:
        professor.is_super_admin = changes["is_super_admin"]

    if mail_changed:
        # sesiones y códigos pendientes quedan invalidados al cambiar el mail
        await db.exec(delete(RefreshToken).where(RefreshToken.id_user == id_professor))
        await db.exec(delete(EmailVerification).where(EmailVerification.id_user == id_professor))

    db.add(user)
    db.add(professor)
    try:
        await db.commit()
    except IntegrityError:  # dos cambios simultáneos al mismo mail
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A professor with this mail already exists")

    return ProfessorPublic(
        id_professor=id_professor,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        email=professor.mail,
        is_super_admin=professor.is_super_admin,
    )