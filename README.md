# Socrates Backend

Backend de **Socrates**, el sistema de gestión educativa del **Seminario Integrador 3K1 2026** de la **UTN FRC**.

Administra alumnos, profesores, comisiones, cursos lectivos, proyectos, entregas, notas, comentarios, asistencia, calendarios, tecnologías y estadísticas. Está construido con **FastAPI**, **SQLModel** y **PostgreSQL**, y se ejecuta con Docker Compose.

- **Frontend:** [rama-ia-dev/SocratesFrontend](https://github.com/rama-ia-dev/SocratesFrontend)
- **API local:** [http://localhost:8000](http://localhost:8000)
- **Swagger / OpenAPI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Documentación interna:** [`docs/`](docs/)

---

## Qué incluye

- Autenticación con access token JWT y refresh token en cookie `HttpOnly`.
- Alta individual y masiva de alumnos, y alta de profesores.
- Comisiones, cursos lectivos, inscripciones y cursadas.
- Proyectos/grupos con privacidad, jefatura, integrantes, estados, enlaces manuales y logo.
- Calendario, clases, actividades y entregas por proyecto.
- Notas históricas, corrección/eliminación de notas y comentarios de entrega.
- Evaluaciones/parciales con notas numéricas 1-10 por alumno.
- Feedback para alumnos y anotaciones internas del staff.
- Asistencia por código, manual, en lote o importada desde el chat.
- Catálogo de tecnologías con imágenes y asociación a proyectos.
- Evaluaciones y estadísticas por proyecto o curso lectivo.
- Estadísticas de alumnos inscriptos/cursando y de tecnologías por ciclo.
- Curso genérico `PRESOCRATICO` para cargar proyectos de ejemplo anteriores a Socrates.

## Stack

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.12 |
| API | FastAPI |
| ORM | SQLModel + SQLAlchemy 2 async |
| Base de datos | PostgreSQL 16 |
| Driver | asyncpg |
| Tests | pytest + pytest-asyncio |
| Contenedores | Docker + Docker Compose |

```text
Frontend (repo separado)
        │  HTTP / JSON
        ▼
Backend FastAPI :8000
        │  SQL async
        ▼
PostgreSQL :5432
```

El frontend es un repositorio independiente: [SocratesFrontend](https://github.com/rama-ia-dev/SocratesFrontend). Consume esta API; el contrato completo está disponible en `/docs` cuando el backend está levantado.

---

## Requisitos

- Docker
- Docker Compose
- Git

No hace falta instalar Python ni PostgreSQL para ejecutar el proyecto con Docker.

## Quickstart

```bash
git clone git@github.com:JoaquinMorais/SocratesBackend.git
cd SocratesBackend

cp .env.example .env
# Editar .env: cambiar POSTGRES_PASSWORD y SECRET_KEY.
# Mantener DATABASE_URL sincronizada con POSTGRES_USER/PASSWORD/DB.

docker compose up --build -d
```

Cuando los contenedores estén sanos:

- API: [http://localhost:8000](http://localhost:8000)
- Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
- Healthcheck: [http://localhost:8000/health](http://localhost:8000/health)
- Archivos de imagen: `http://localhost:8000/media/...`

La primera vez se crean las tablas y se carga el seed. Los cambios en archivos `.py` se recargan automáticamente.

### Variables de entorno

El archivo `.env` **no se versiona**. `.env.example` contiene placeholders seguros; no uses esos valores en producción.

Variables principales:

| Variable | Uso |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Credenciales de PostgreSQL |
| `DATABASE_URL` | URL async hacia PostgreSQL; debe coincidir con las credenciales anteriores |
| `SECRET_KEY` | Firma de los JWT; usar un valor largo y aleatorio |
| `SEED_FILE` | Seed que se carga con la base vacía: `seed.json` (por defecto) o `seed_real.json` |
| `EMAIL_BACKEND` | `console` para ver mails en logs o `smtp` para enviarlos |
| `EMAIL_DEV_REDIRECT` | Redirige todos los mails a una dirección en desarrollo |
| `MEDIA_DIR`, `MEDIA_BASE_URL` | Almacenamiento y URL pública de imágenes |
| `ATTENDANCE_*` | Vencimiento del código y tolerancias de importación |

Para generar una clave:

```bash
openssl rand -hex 32
```

Ejemplo de `.env` para desarrollo:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=mi-password-local
POSTGRES_DB=socrates_db
DATABASE_URL=postgresql+asyncpg://postgres:mi-password-local@db:5432/socrates_db
SECRET_KEY=una-clave-larga-y-aleatoria
EMAIL_BACKEND=console
```

Los mails de prueba se leen con:

```bash
docker compose logs -f backend
```

---

## Tests

Con el backend levantado:

```bash
docker compose exec backend pytest -q
```

Casos puntuales:

```bash
docker compose exec backend pytest tests/test_auth.py
docker compose exec backend pytest tests/test_auth.py -k refresh
docker compose exec backend pytest -x
```

Los tests usan una base temporal por corrida y un savepoint por test. **No tocan la base principal**.

Para correr dos sesiones sin que se pisen:

```bash
# sesión de historias
docker compose run --rm --no-deps -T -e TEST_DB_SUFFIX=historias backend python -m pytest -q

# sesión de bugs
docker compose run --rm --no-deps -T -e TEST_DB_SUFFIX=bugs backend python -m pytest -q
```

La documentación de qué prueba cada archivo está en [`docs/tests.md`](docs/tests.md).

---

## Usuarios del seed

El seed solo se carga cuando la base está vacía. El seed realista (`data/seed.json`) usa la contraseña `Test1234!` para todos sus usuarios de prueba; la comisión real (`data/seed_real.json`) usa `Pass1234` y se activa con `SEED_FILE=seed_real.json`.

| Rol | Mail |
|---|---|
| Super admin | `marta.rodriguez@frc.utn.edu.ar` |
| Profesor | `carlos.ruiz@frc.utn.edu.ar` |
| Alumno | `100001@sistemas.frc.utn.edu.ar` |
| Alumno | `100002@sistemas.frc.utn.edu.ar` |

Los alumnos usan el patrón `{legajo}@sistemas.frc.utn.edu.ar`. Las cuentas nuevas no tienen contraseña: se crea o restablece con el código enviado por mail.

> Estas credenciales son exclusivamente para desarrollo y pruebas.

El seed realista incluye 200 alumnos, 16 profesores, 10 cursos lectivos reales (2024-2026), el curso genérico `PRESOCRATICO` (2000), proyectos con estados e historial, entregas, tecnologías, calendarios y asistencias.

`data/seed_real.json` es la comisión real 3K1 2026: 97 alumnos en 18 grupos, 5 alumnos inscriptos en 3K4 que cursan en 3K1, Marta y María Cecilia como super admin, Daniel, María Cecilia y Rita asignados a 3K1, proyectos en `in_progress`, calendario de clases de agosto a noviembre (martes presencial y miércoles virtual), 6 actividades y entregas simuladas con estados y notas variados. Para usarla, definir `SEED_FILE=seed_real.json` y recrear la base con `docker compose down -v`.

Para volver a la base inicial:

```bash
docker compose down -v
docker compose up --build -d
```

---

## Comandos habituales

```bash
# Levantar en segundo plano
docker compose up -d

# Primera vez o cambios en Dockerfile/requirements.txt
docker compose up --build -d

# Ver logs del backend
docker compose logs -f backend

# Ver estado
docker compose ps

# Apagar sin borrar la base
docker compose down

# Apagar y borrar la base y el volumen
docker compose down -v
```

### Cuándo recrear

| Cambio | Acción |
|---|---|
| Archivo `.py` | Nada; se recarga solo |
| `requirements.txt` o `Dockerfile` | `docker compose up --build -d` |
| `docker-compose.yml` o `.env` | `docker compose up -d` |
| Columnas de una tabla existente | `docker compose down -v` y volver a levantar |

El proyecto usa `create_all`, que crea tablas nuevas pero **no modifica tablas existentes**. Alembic todavía está pendiente.

---

## Estructura

```text
.
├── index.py              # App FastAPI, routers, CORS, /media y lifespan
├── config/               # Settings y conexión a la base
├── models/               # Tablas SQLModel y estados de dominio
├── schemas/              # Validación de entrada y respuestas públicas
├── routes/               # Endpoints delgados
├── utils/                # Lógica de negocio y reglas
├── data/                 # seed.json, seed_real.json y seed_test.json
├── tests/                # Suite de pytest
├── docs/                 # Documentación del proyecto
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

Documentación recomendada:

- [`docs/PROJECT.md`](docs/PROJECT.md): dominio, permisos, flujos y estado.
- [`docs/STRUCTURE.md`](docs/STRUCTURE.md): mapa de archivos y responsabilidades.
- [`docs/TEMPLATES.md`](docs/TEMPLATES.md): plantillas para recursos nuevos.
- [`docs/tests.md`](docs/tests.md): qué prueba cada test.
- [`docs/WORKFLOW.md`](docs/WORKFLOW.md): orden de trabajo para una historia.
- [`docs/commands.md`](docs/commands.md): comandos de Docker.

---

## Roles y permisos

| Rol | Alcance principal |
|---|---|
| Alumno | Su proyecto, sus entregas, su asistencia y su calendario |
| Profesor | Sus cursos lectivos, proyectos, notas, asistencia y reportes |
| Super admin | Gestión completa del sistema |

Los permisos que dependen del dato —por ejemplo, “profesor asignado a este curso”— se resuelven con la clase `Access` de `utils/projects.py`. Las lecturas suelen requerir solo login; las escrituras exigen profesor, super admin o privilegios del proyecto.

La autenticación usa:

- `POST /auth/login` → access token JWT de 15 minutos.
- Header `Authorization: Bearer <token>`.
- Refresh token opaco en cookie `HttpOnly`, rotado en cada uso.

---

## Desarrollo

Antes de cambiar código:

1. Leer [`AGENTS.md`](AGENTS.md) y [`docs/WORKFLOW.md`](docs/WORKFLOW.md).
2. Si se crea un recurso, usar [`docs/TEMPLATES.md`](docs/TEMPLATES.md).
3. Mantener las rutas delgadas y la lógica en `utils/`.
4. Todo acceso a base de datos debe ser asíncrono.
5. Agregar o actualizar tests para cada cambio de comportamiento.
6. Actualizar `docs/PROJECT.md`, `docs/STRUCTURE.md` y `docs/tests.md` cuando corresponda.
7. No subir `.env` ni secretos.

Antes de abrir un PR, correr la suite completa y revisar `/docs` para confirmar que los endpoints nuevos tienen descripción y errores documentados.

---

## Problemas frecuentes

**El backend no levanta o faltan variables**

Revisar que exista `.env` y que `DATABASE_URL` coincida con `POSTGRES_*`:

```bash
cp .env.example .env
docker compose up -d
docker compose logs backend
```

**Cambié una columna y la base no se actualiza**

`create_all` no altera tablas existentes:

```bash
docker compose down -v
docker compose up --build -d
```

**No llegan los mails**

En desarrollo se imprimen en consola:

```bash
docker compose logs -f backend
```

También se puede configurar `EMAIL_DEV_REDIRECT` o `EMAIL_BACKEND=smtp`.

**El puerto 8000 está ocupado**

Cambiar el mapeo en `docker-compose.yml` o detener el proceso que lo esté usando.

**Quedaron bases de test huérfanas**

Se pueden listar y borrar desde el contenedor de PostgreSQL, o eliminar todo el volumen con `docker compose down -v`.

---

## Estado del proyecto

El backend cubre autenticación, usuarios, cursos, proyectos, integrantes, entregas, notas, comentarios, asistencia, calendarios, tecnologías, imágenes, evaluaciones y estadísticas. La suite actual supera los 850 tests.

Los pendientes y decisiones abiertas están en [`docs/PROJECT.md`](docs/PROJECT.md#pendiente).
