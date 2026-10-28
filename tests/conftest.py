import os
import shutil
import tempfile
from datetime import date

# Estas variables tienen que fijarse ANTES de importar la app: el engine y el
# montaje de /media se crean al importar.
from sqlalchemy.engine import make_url

_main = make_url(os.environ["DATABASE_URL"])
TEST_DB = f"{_main.database}_test"
os.environ["DATABASE_URL"] = _main.set(database=TEST_DB).render_as_string(hide_password=False)
os.environ["EMAIL_BACKEND"] = "console"
os.environ["EMAIL_DEV_REDIRECT"] = ""
os.environ["OTP_COOLDOWN_SECONDS"] = "0"
os.environ["SEND_WELCOME_EMAILS"] = "true"

# Los archivos de imagen van a un directorio temporal de la sesión.
MEDIA_DIR_PATH = tempfile.mkdtemp(prefix="socrates-media-")
os.environ["MEDIA_DIR"] = MEDIA_DIR_PATH
os.environ["MEDIA_BASE_URL"] = "http://test/media"

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

import config.database as database  # noqa: E402
import utils.security as security  # noqa: E402
from config.database import engine, get_session  # noqa: E402
from index import app  # noqa: E402
from models import Professor, User  # noqa: E402
from tests.helpers import PASSWORD  # noqa: E402
from utils.seed import DATA_DIR, load_seed  # noqa: E402

# En tests no hace falta el costo de Argon2 de producción (hash/verify ~160 ms).
# Un hasher barato mantiene la misma lógica de auth pero acelera el seed y los logins.
security._ph = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)


class _SessionLocalProxy:
    """Fábrica de sesiones que delega en la sesión bindeada a la conexión de test.

    Los test modules hacen `from config.database import SessionLocal` al importarse,
    antes de que corran los fixtures, así que publicamos este proxy en
    `config.database` a nivel de módulo: así esos imports y `get_session` de la app
    comparten la misma conexión, y cada test corre dentro de un savepoint que se
    revierte al terminar.
    """

    def __init__(self) -> None:
        self._factory = None

    def __call__(self, *args, **kwargs):
        if self._factory is None:
            raise RuntimeError("La sesión de test todavía no está inicializada")
        return self._factory(*args, **kwargs)


session_local_proxy = _SessionLocalProxy()
database.SessionLocal = session_local_proxy

TEST_SEED_PATH = DATA_DIR / "seed_test.json"


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
    """Crea la BD de test una sola vez y la siembra una sola vez por sesión.

    Toda la suite comparte una conexión con una transacción externa. Cada test
    corre dentro de un savepoint (ver `clean_db`) que se revierte, así que nunca
    hace falta volver a truncar ni sembrar entre tests.
    """
    assert TEST_DB.endswith("_test"), "Nunca se debe tocar la BD principal"
    await _admin(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    await _admin(f'CREATE DATABASE "{TEST_DB}"')

    connection = await engine.connect()
    transaction = await connection.begin()
    await connection.run_sync(SQLModel.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session_local_proxy._factory = session_factory

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    async with session_local_proxy() as session:
        await load_seed(session, seed_path=TEST_SEED_PATH)

    yield connection

    app.dependency_overrides.clear()
    session_local_proxy._factory = None
    await transaction.rollback()
    await connection.close()
    await engine.dispose()
    shutil.rmtree(MEDIA_DIR_PATH, ignore_errors=True)
    await _admin(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')


@pytest_asyncio.fixture(autouse=True)
async def clean_db(database):
    """Aísla cada test con un savepoint; el seed de la sesión nunca se toca."""
    savepoint = await database.begin_nested()
    try:
        yield
    finally:
        await savepoint.rollback()


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
        async with session_local_proxy() as s:
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