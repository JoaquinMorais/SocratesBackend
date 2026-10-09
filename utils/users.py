from sqlmodel import col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import Professor, User
from schemas.user import UserListItem, UserPublic, UserUpdate


def get_role(user: User) -> str | None:
    return "student" if user.student else "professor" if user.professor else None


def to_public(user: User) -> UserPublic:
    return UserPublic(
        id_user=user.id_user,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        email=user.get_mail(),
        role=get_role(user),
        is_super_admin=user.professor.is_super_admin if user.professor else None,
    )


def to_list_item(user: User) -> UserListItem:
    return UserListItem(
        id_user=user.id_user,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        email=user.get_mail(),
        role=get_role(user),
        enrollment_year=user.student.enrollment_year if user.student else None,
        is_super_admin=user.professor.is_super_admin if user.professor else None,
    )


async def update_user(db: AsyncSession, user: User, data: UserUpdate) -> User:
    changes = data.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    db.add(user)
    await db.commit()
    return user


async def list_users(
    db: AsyncSession, *, role: str | None, q: str | None, limit: int, offset: int
) -> tuple[list[User], int]:
    conditions = []
    if role == "student":
        conditions.append(User.student.has())
    elif role == "professor":
        conditions.append(User.professor.has())

    if q:
        like = f"%{q.strip()}%"
        search = [
            col(User.first_name).ilike(like),
            col(User.last_name).ilike(like),
            User.professor.has(col(Professor.mail).ilike(like)),
        ]
        if q.strip().isdigit():
            search.append(User.legajo == int(q.strip()))
        conditions.append(or_(*search))

    total = (
        await db.exec(select(func.count()).select_from(User).where(*conditions))
    ).one()
    users = (
        await db.exec(
            select(User)
            .where(*conditions)
            .order_by(col(User.last_name), col(User.first_name), col(User.id_user))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(users), total