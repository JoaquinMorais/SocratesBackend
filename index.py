from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel
from fastapi.middleware.cors import CORSMiddleware



import models  # noqa: F401  (registra las tablas)
from routes.__init__ import * 
from config.database import SessionLocal, engine
from utils.seed import load_seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with SessionLocal() as session:
        await load_seed(session)
    yield
    await engine.dispose()


app = FastAPI(
    title="Socrates API",
    description=(
        "Backend de Socrates.\n\n"
        "**Autenticación:** `POST /auth/login` devuelve un `access_token` (JWT, 15 min) "
        "que se envía en el header `Authorization: Bearer <token>`. El refresh token "
        "viaja en una cookie `HttpOnly` que el navegador gestiona solo; para renovar "
        "el access se llama a `POST /auth/refresh` sin body.\n\n"
        "**Login:** se usa el mail completo. Alumnos: `{legajo}@sistemas.frc.utn.edu.ar`. "
        "Profesores: su mail propio."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "auth", "description": "Login, sesión y contraseña."},
        {"name": "me", "description": "Datos del usuario logueado."},
        {"name": "users", "description": "Consulta de usuarios (solo super admin)."},
        {"name": "students", "description": "Alta y edición de alumnos (profesores)."},
        {"name": "professors", "description": "Alta y edición de profesores (solo super admin)."},
        {"name": "sections", "description": "Comisiones (consulta: cualquier usuario; escritura: super admin)."},
        {"name": "section-years", "description": "Cursos lectivos: comisión + año (consulta: cualquier usuario; escritura: super admin)."},
        {"name": "professor-section-years", "description": "Profesores asignados a cursos lectivos (consulta: cualquier usuario; escritura: super admin)."},
                {"name": "projects", "description": "Proyectos (grupos) de cada curso lectivo; el detalle depende de la privacidad."},
        ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(users_router)
app.include_router(students_router)
app.include_router(professors_router)
app.include_router(sections_router)
app.include_router(section_years_router)
app.include_router(professor_section_years_router)
app.include_router(projects_router)

@app.get("/health")
async def health():
    return {"status": "ok"}