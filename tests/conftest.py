import os
from datetime import date

# Estas variables tienen que fijarse ANTES de importar la app: el engine se crea al importar.
from sqlalchemy.engine import make_url

_main = make_url(os.environ["DATABASE_URL"])
TEST_DB = f"{_main.database}_test"
os.environ["DATABASE_URL"] = _main.set(database=TEST_DB).render_as_string(hide_password=False)
os.environ["EMAIL_BACKEND"] = "console"
os.environ["EMAIL_DEV_REDIRECT"] = ""
os.environ["OTP_COOLDOWN_SECONDS"] = "0"
os.environ["SEND_WELCOME_EMAILS"] = "true"

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from config.database import SessionLocal, engine  # noqa: E402
from index import app  # noqa: E402
from models import Professor, User  # noqa: E402
from tests.helpers import PASSWORD  # noqa: E402
from utils.seed import load_seed  # noqa: E402


async def _admin(sql: str) -> None:
    conn = await asyncpg.connect(
        user=_main.username,
        password=_main.password,
        host=_main.host,
        port=_main.port or 5432,
        database="postgres",
    )
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def database():
    assert TEST_DB.endswith("_test"), "Nunca se debe tocar la BD principal"
    await _admin(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    await _admin(f'CREATE DATABASE "{TEST_DB}"')
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    await engine.dispose()
    await _admin(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')


@pytest_asyncio.fixture(autouse=True)
async def clean_db(database):
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    async with SessionLocal() as session:
        await load_seed(session)


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """Intercepta los mails: en vez de enviarse quedan en esta lista."""
    sent: list[dict] = []

    async def fake_send_email(to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("utils.email.send_email", fake_send_email)
    return sent


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def login(client):
    async def _login(mail: str, password: str = PASSWORD) -> dict:
        r = await client.post("/auth/login", json={"email": mail, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


@pytest.fixture
def make_professor():
    """Crea un profesor directo en la BD (para probar permisos)."""

    async def _make(mail: str, is_super_admin: bool = False, legajo: int = 300000) -> str:
        async with SessionLocal() as s:
            user = User(
                first_name="Test", last_name="Prof", legajo=legajo, birth_date=date(1980, 1, 1)
            )
            user.set_password(PASSWORD)
            s.add(user)
            await s.flush()
            s.add(Professor(id_professor=user.id_user, mail=mail, is_super_admin=is_super_admin))
            await s.commit()
        return mail

    return _make


def pytest_collection_modifyitems(items):
    session_loop = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if pytest_asyncio.is_async_test(item):
            item.add_marker(session_loop, append=False)