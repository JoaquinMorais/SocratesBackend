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
        {"name": "me", "description": "Datos del usuario logueado y su proyecto (`GET /me/project`, solo alumnos): el grupo donde es miembro con integrantes, responsables y jefe, y sus solicitudes de ingreso pendientes o rechazadas."},
        {"name": "users", "description": "Consulta de usuarios (solo super admin)."},
        {"name": "students", "description": "Alta, edición y consulta de alumnos (profesores; la consulta muestra el grupo y admite super admin). Cada grupo indica si el alumno es jefe (`is_leader`) y su `status` de membresía; la consulta se filtra por esos estados (por defecto `active` y `finished`)."},
        {"name": "professors", "description": "Alta y edición de profesores (solo super admin)."},
        {"name": "sections", "description": "Comisiones (consulta: cualquier usuario; escritura: super admin)."},
        {"name": "section-years", "description": "Cursos lectivos: comisión + año, con el mínimo y máximo de estudiantes por grupo (consulta: cualquier usuario; escritura: super admin)."},
        {"name": "professor-section-years", "description": "Profesores asignados a cursos lectivos (consulta: cualquier usuario; escritura: super admin)."},
        {"name": "projects", "description": "Proyecto (grupo) de un curso lectivo, con su privacidad. El proyecto nace `uninsured` (Desasegurado) y pasa por `in_idea`, `in_progress`, `pending_approval`, `rejected` (los cuatro son 'insured' o asegurados) hasta `approved` o `cancelled` (finales). Mientras está `uninsured` se trata siempre como público, sin importar su privacidad. Los privilegiados (profesor del curso lectivo, super admin y miembros `active`/`finished`) pueden modificar sus atributos mientras no esté en un estado final. Cada membresía alumno-proyecto también tiene su estado (`active`, `pending_approval`, `abandoned`, `finished`, `expelled` o `rejected`). El historial de transiciones se consulta con `GET /projects/{id}/status-history`. `GET /projects/{id}/overview` devuelve el proyecto con sus integrantes, sus responsables (los profesores de su curso lectivo, sin mail) y su jefe (`leader`, o `null` si no tiene), con la misma visibilidad según privacidad: en `protected` el no privilegiado ve la información básica y también los integrantes, los responsables y el jefe. `POST /projects/{id}/insure` registra el aseguramiento (lo pueden hacer el jefe del grupo, un profesor de ese curso lectivo o un super admin) y a partir de ahí ya no se unen integrantes nuevos. Las transiciones de estado (`uninsure`, `start`, `submit`, `approve`, `reject`, `retry` y `cancel`) las puede hacer un profesor del curso lectivo o un super admin."},
        {"name": "members", "description": "Integrantes de un proyecto. Un alumno se une a un grupo `uninsured` (`POST /projects/{id}/members`); si el grupo no tiene jefe entra como jefe y `active`, si no queda `pending_approval`. Solo el jefe acepta o rechaza solicitudes (`PATCH /projects/{id}/members/{id_student_project}`). Mientras el proyecto está `uninsured`, cualquier integrante `active` puede abandonar (`POST .../abandon`) y un profesor del curso lectivo o super admin puede expulsar (`POST .../expel`); en cualquier estado no final, el jefe puede delegar la jefatura a otro integrante `active` (`POST .../leader`). Si el jefe sale o es expulsado, la jefatura pasa al integrante `active` más antiguo. Un alumno solo puede ser `member` (`active`/`finished`) de un grupo en todo el sistema."},
        {"name": "technologies", "description": "Tecnologías con nombre y descripción opcional (consulta: cualquier usuario; alta, edición y baja: profesores y super admin). El nombre es obligatorio (máximo 100 caracteres) y no puede repetirse sin distinguir mayúsculas. Una tecnología que está en uso por algún proyecto no se puede eliminar."},
        {"name": "project-technologies", "description": "Vínculo proyecto-tecnología (`POST /projects/{id}/technologies`, en lote con `.../bulk` y `DELETE /projects/{id}/technologies/{id_technology}`). Agregar o quitar corresponde a los privilegiados del proyecto (miembros `active`/`finished`, profesor del curso lectivo o super admin) mientras el proyecto no esté en un estado final; la consulta sigue la privacidad del proyecto (en `private` solo los privilegiados)."},
        {"name": "statuses", "description": "Estados por ámbito (`project`, `student_project`): `code`, `name`, `description`, `is_final` e `is_insured` (si el estado de proyecto cuenta como asegurado). La consulta sirve para etiquetas y filtros; todavía no hay alta ni edición."},
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
app.include_router(student_projects_router)
app.include_router(technologies_router)
app.include_router(project_technologies_router)
app.include_router(statuses_router)

@app.get("/health")
async def health():
    return {"status": "ok"}