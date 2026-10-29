from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel
from fastapi.middleware.cors import CORSMiddleware



import models  # noqa: F401  (registra las tablas)
from routes.__init__ import *
from config.database import SessionLocal, engine
from config.settings import settings
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
        {"name": "me", "description": "Datos del usuario logueado, su calendario (`GET /me/calendar`: clases y actividades de sus cursos actuales), su asistencia (`GET /me/attendance`, solo alumnos), su curso lectivo actual (`GET /me/section-year`, profesor o alumno, con el año más reciente) y los proyectos de ese curso (`GET /me/section-year/projects`, con la privacidad de siempre). Para alumnos, también su proyecto (`GET /me/project`): el grupo donde es miembro con integrantes, responsables y jefe, y sus solicitudes de ingreso pendientes o rechazadas."},
        {"name": "users", "description": "Consulta de usuarios (solo super admin) y eliminación de usuarios cargados por error. Un alumno con membresía vigente, un profesor asignado a un curso lectivo o un super admin no se pueden eliminar."},
        {"name": "students", "description": "Alta, edición y consulta de alumnos (profesores; la consulta muestra el grupo y admite super admin). Cada grupo indica si el alumno es jefe (`is_leader`) y su `status` de membresía; la consulta se filtra por esos estados (por defecto `active` y `finished`)."},
        {"name": "professors", "description": "Alta, edición y eliminación de profesores (solo super admin). Un super admin o un profesor asignado a un curso lectivo no se puede eliminar."},
        {"name": "sections", "description": "Comisiones (consulta: cualquier usuario; escritura: super admin)."},
        {"name": "section-years", "description": "Cursos lectivos: comisión + año, con el mínimo y máximo de estudiantes por grupo (consulta: cualquier usuario; escritura: super admin)."},
        {"name": "professor-section-years", "description": "Profesores asignados a cursos lectivos (consulta: cualquier usuario; escritura: super admin)."},
        {"name": "attendance", "description": "Asistencia por clase. El profesor habilita la toma (código de 6 dígitos que vence) o marca a mano; el alumno con cursada en el curso anota el código desde la app. Solo hay fila cuando el alumno está presente; la ausencia es la falta de fila. La lista de la clase es solo para el profesor del curso/super admin, y el alumno tiene su historial en `GET /me/attendance`. También se puede importar la asistencia desde el chat de la clase (texto/CSV con `LEGAJO-ApellidoNombre`, legajo exacto y nombre tolerante), en dos pasos: preview y confirmación (`method=transcript`)."},
        {"name": "activities", "description": "Actividades/entregas del curso lectivo, con fecha y hora de entrega (opcional). Son de todo el curso y no se distinguen por grupo; se gestionan desde el calendario del curso (profesor asignado o super admin) y las ven los alumnos del curso. `GET /me/calendar` devuelve las clases y actividades de los cursos actuales del usuario."},
        {"name": "calendar", "description": "Calendario del curso lectivo (1 a 1): cada clase es una fila concreta, presencial o virtual. Se crean de a una o en lote (todos los martes y miércoles entre dos fechas), y se modifican o borran de a una o en lote. Un feriado o una suspensión es editar o borrar la clase. Lo gestionan el profesor del curso y el super admin; lo ven los alumnos del curso (cursada o grupo)."},
        {"name": "student-section-years", "description": "Cursadas: qué alumno cursó qué curso lectivo (consulta: profesores y super admin; escritura: super admin). Un alumno puede cursar varios años lectivos y un curso lectivo tiene muchos alumnos; el mismo par no se repite. Se puede indicar al crear un alumno (`id_section_year` en `POST /students` o por fila en `POST /students/bulk`). Un curso lectivo con cursadas no se puede eliminar hasta quitarlas."},
        {"name": "projects", "description": "Proyecto (grupo) de un curso lectivo, con su privacidad. El proyecto nace `uninsured` (Desasegurado) y pasa por `in_idea`, `in_progress`, `pending_approval`, `rejected` (los cuatro son 'insured' o asegurados) hasta `approved` o `cancelled` (finales). Mientras está `uninsured` se trata siempre como público, sin importar su privacidad. Los privilegiados (profesor del curso lectivo, super admin y miembros `active`/`finished`) pueden modificar sus atributos mientras no esté en un estado final. Cada membresía alumno-proyecto también tiene su estado (`active`, `pending_approval`, `abandoned`, `finished`, `expelled` o `rejected`). El historial de transiciones se consulta con `GET /projects/{id}/status-history`. `GET /projects/{id}/overview` devuelve el proyecto con sus integrantes, sus responsables (los profesores de su curso lectivo, sin mail) y su jefe (`leader`, o `null` si no tiene), con la misma visibilidad según privacidad: en `protected` el no privilegiado ve la información básica y también los integrantes, los responsables y el jefe. `POST /projects/{id}/insure` registra el aseguramiento (lo pueden hacer el jefe del grupo, un profesor de ese curso lectivo o un super admin) y a partir de ahí ya no se unen integrantes nuevos. Las transiciones de estado (`uninsure`, `start`, `submit`, `approve`, `reject`, `retry` y `cancel`) las puede hacer un profesor del curso lectivo o un super admin."},
        {"name": "members", "description": "Integrantes de un proyecto. Un alumno se une a un grupo `uninsured` (`POST /projects/{id}/members`); si el grupo no tiene jefe entra como jefe y `active`, si no queda `pending_approval`. Solo el jefe acepta o rechaza solicitudes (`PATCH /projects/{id}/members/{id_student_project}`). Mientras el proyecto está `uninsured`, cualquier integrante `active` puede abandonar (`POST .../abandon`) y un profesor del curso lectivo o super admin puede expulsar (`POST .../expel`); en cualquier estado no final, el jefe puede delegar la jefatura a otro integrante `active` (`POST .../leader`). Si el jefe sale o es expulsado, la jefatura pasa al integrante `active` más antiguo. Un alumno solo puede ser `member` (`active`/`finished`) de un grupo en todo el sistema."},
        {"name": "technologies", "description": "Tecnologías con nombre y descripción opcional (consulta: cualquier usuario; alta, edición y baja: profesores y super admin). El nombre es obligatorio (máximo 100 caracteres) y no puede repetirse sin distinguir mayúsculas. Una tecnología que está en uso por algún proyecto no se puede eliminar. Cada tecnología puede tener una imagen: se acepta jpeg, png o webp (máximo 5 MB) y siempre se guarda convertida a WebP y servida bajo `/media`; se sube con el alta/edición en multipart, con `PUT /technologies/{id}/image` o vinculando una imagen ya subida (`id_image`). Quitarla o reemplazarla borra el archivo."},
        {"name": "images", "description": "Imágenes subidas al sistema (profesores y super admin): multipart con el archivo (`image/jpeg`, `image/png` o `image/webp`, máximo 5 MB) que se guarda siempre convertido a WebP y se sirve en `/media/{key}`. Consulta libre para cualquier usuario logueado; borrar una imagen asignada a una tecnología responde 409. Cada tecnología tiene a lo sumo una imagen (1:1)."},
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
app.include_router(student_section_years_router)
app.include_router(calendars_router)
app.include_router(calendar_classes_router)
app.include_router(section_activities_router)
app.include_router(activities_router)
app.include_router(attendance_router)
app.include_router(projects_router)
app.include_router(student_projects_router)
app.include_router(technologies_router)
app.include_router(images_router)
app.include_router(project_technologies_router)
app.include_router(statuses_router)

# Archivos de imagen servidos en `/media/{key}` (se crea el directorio al arrancar).
Path(settings.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")

@app.get("/health")
async def health():
    return {"status": "ok"}