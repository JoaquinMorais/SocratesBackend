import json
from datetime import date
from pathlib import Path

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import Professor, Student, User

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "seed.json"


def _build_user(item: dict) -> User:
    user = User(
        first_name=item["first_name"],
        last_name=item["last_name"],
        legajo=item["legajo"],
        birth_date=date.fromisoformat(item["birth_date"]),
    )
    if item.get("password"):
        user.set_password(item["password"])
    return user


async def load_seed(session: AsyncSession) -> None:
    existing = (await session.exec(select(User.id_user).limit(1))).first()
    if existing is not None:
        return

    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    for item in data.get("students", []):
        user = _build_user(item)
        session.add(user)
        await session.flush()  # obtiene id_user
        session.add(
            Student(id_student=user.id_user, enrollment_year=item["enrollment_year"])
        )

    for item in data.get("professors", []):
        user = _build_user(item)
        session.add(user)
        await session.flush()
        session.add(
            Professor(
                id_professor=user.id_user,
                mail=item["mail"].strip().lower(),
                is_super_admin=item.get("is_super_admin", False),
            )
        )

    await session.commit()