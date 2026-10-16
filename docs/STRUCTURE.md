# Estructura del proyecto

Repositorio: `socrates-backend`.

## Árbol

```
socrates-backend/
├── index.py                      # Punto de entrada: crea la app, registra los routers
├── Dockerfile
├── docker-compose.yml            # Servicios: db (Postgres) y backend
├── requirements.txt
├── pytest.ini
├── .env                          # Variables de entorno (no se sube al repo)
├── .gitignore
├── .dockerignore
├── README.md
├── comands.md                    # Comandos de Docker de uso diario
├── PROJECT.md                    # Idea y alcance del proyecto
├── STRUCTURE.md                  # Este archivo
├── tests.md                      # Documentación de los tests
│
├── config/                       # Configuración de la app
│   ├── __init__.py
│   ├── settings.py
│   └── database.py
│
├── data/
│   └── seed.json                 # Usuarios de ejemplo que se cargan al arrancar
│
├── models/                       # Tablas de la base de datos (SQLModel)
│   ├── __init__.py
│   ├── user.py
│   ├── student.py
│   ├── professor.py
│   ├── section.py
│   ├── section_year.py
│   ├── professor_section_year.py
│   ├── project.py
│   ├── student_project.py
│   ├── token.py
│   └── email_verification.py
│
├── schemas/                      # Formatos de entrada y salida de la API
│   ├── __init__.py
│   ├── auth.py
│   ├── user.py
│   ├── student.py
│   ├── professor.py
│   ├── section.py
│   ├── section_year.py
│   ├── professor_section_year.py
│   └── project.py
│
├── routes/                       # Endpoints (APIRouters)
│   ├── __init__.py
│   ├── auth.py
│   ├── me.py
│   ├── users.py
│   ├── students.py
│   ├── professors.py
│   ├── sections.py
│   ├── section_years.py
│   ├── professor_section_years.py
│   └── projects.py
│
├── utils/                        # Lógica reutilizable que invocan las rutas
│   ├── __init__.py
│   ├── security.py
│   ├── auth.py
│   ├── permissions.py
│   ├── email.py
│   ├── verification.py
│   ├── seed.py
│   ├── users.py
│   ├── students.py
│   ├── professors.py
│   ├── sections.py
│   ├── section_years.py
│   ├── professor_section_years.py
│   └── projects.py
│
└── tests/                        # Tests automáticos (pytest)
    ├── __init__.py
    ├── conftest.py
    ├── helpers.py
    ├── test_auth.py
    ├── test_users.py
    ├── test_students.py
    ├── test_professors.py
    ├── test_sections.py
    ├── test_section_years.py
    ├── test_professor_section_years.py
    └── test_projects.py
```

## Cómo se reparten las responsabilidades

Cada recurso sigue el mismo recorrido, de afuera hacia adentro:

`routes/` recibe la request, `schemas/` la valida, `utils/` aplica la lógica y las reglas de negocio, y `models/` define cómo se guarda en la base de datos.

Las rutas son delgadas: declaran el endpoint, sus permisos y su documentación, y delegan en `utils/`. Así la misma lógica se reutiliza desde varias rutas sin repetir código.

## Raíz

| Archivo | Para qué sirve |
|---|---|
| `index.py` | Crea la aplicación FastAPI, configura CORS y la documentación, registra todos los routers y, al arrancar, crea las tablas y carga el seed. |
| `Dockerfile` | Imagen del backend (Python + dependencias + código). |
| `docker-compose.yml` | Levanta el backend y PostgreSQL, con la BD persistida en un volumen. |
| `requirements.txt` | Dependencias de Python. |
| `pytest.ini` | Configuración de pytest (modo async y alcance del event loop). |
| `.env` | Credenciales y parámetros (base de datos, claves, tiempos, mail). No se versiona. |
| `comands.md` | Comandos de Docker de uso diario. |
| `PROJECT.md` | Idea del proyecto, dominio, flujos, permisos y estado. |
| `tests.md` | Qué verifica cada test. |

## `config/`

| Archivo | Para qué sirve |
|---|---|
| `settings.py` | Lee las variables de entorno y las expone como `settings`. |
| `database.py` | Motor async de SQLAlchemy, sesión y la dependencia `db_dependency` que usan las rutas. |

## `data/`

| Archivo | Para qué sirve |
|---|---|
| `seed.json` | Alumnos y un profesor super admin de ejemplo, para poder probar sin cargar nada. Solo se carga si la BD está vacía. |

## `models/`

| Archivo | Tabla | Contenido |
|---|---|---|
| `user.py` | `users` | Datos comunes de todo usuario y manejo de la contraseña (`set_password`, `verify_password`, `get_mail`). |
| `student.py` | `students` | Datos del alumno (año de ingreso); su mail se calcula por legajo. |
| `professor.py` | `professors` | Datos del profesor (mail propio e indicador de super admin). |
| `section.py` | `sections` | Comisión (por ejemplo `3K1`). |
| `section_year.py` | `section_years` | Curso lectivo: comisión + año. |
| `professor_section_year.py` | `professor_section_years` | Asignación de un profesor a un curso lectivo. |
| `project.py` | `projects` | Proyecto (grupo) de un curso lectivo, con su privacidad. |
| `student_project.py` | `student_projects` | Alumnos que integran un proyecto. |
| `token.py` | `refresh_tokens` | Refresh tokens vigentes, guardados hasheados. |
| `email_verification.py` | `email_verifications` | Códigos de verificación por mail (OTP), hasheados. |

## `schemas/`

Definen qué datos acepta y devuelve cada endpoint (altas, modificaciones, respuestas públicas y listados paginados). Hay un archivo por recurso: `auth`, `user`, `student`, `professor`, `section`, `section_year`, `professor_section_year` y `project`.

## `routes/`

| Archivo | Prefijo | Qué expone |
|---|---|---|
| `auth.py` | `/auth` | Login, refresh, logout y flujo de contraseña por código. |
| `me.py` | `/me` | Datos del usuario logueado y modificación de sus datos personales. |
| `users.py` | `/users` | Listado de usuarios registrados (super admin). |
| `students.py` | `/students` | Alta de alumnos (individual y masiva) y su modificación. |
| `professors.py` | `/professors` | Alta de profesores y su modificación (super admin). |
| `sections.py` | `/sections` | CRUD de comisiones. |
| `section_years.py` | `/section-years` | CRUD de cursos lectivos. |
| `professor_section_years.py` | `/professor-section-years` | CRUD de asignaciones de profesores a cursos lectivos. |
| `projects.py` | `/projects` | Crear (individual y masivo), listar, consultar y eliminar proyectos. |

`routes/__init__.py` reúne todos los routers para que `index.py` los registre.

## `utils/`

| Archivo | Para qué sirve |
|---|---|
| `security.py` | Hash de contraseñas (argon2), tokens JWT y de refresh, y códigos OTP. |
| `auth.py` | Cookie de refresh, búsqueda de usuario por mail, emisión de tokens y la dependencia `user_dependency`. |
| `permissions.py` | Dependencias de rol: `professor_dependency`, `super_admin_dependency` y `student_dependency`. |
| `email.py` | Envío de mails (por consola o por SMTP): código de verificación y bienvenida. |
| `verification.py` | Creación y consumo de códigos OTP (vencimiento, intentos y espera entre pedidos). |
| `seed.py` | Carga inicial desde `data/seed.json`. |
| `users.py` | Armado de respuestas de usuario, edición de datos propios y listado con filtros. |
| `students.py` | Alta masiva de alumnos y modificación de un alumno. |
| `professors.py` | Alta y modificación de profesores. |
| `sections.py` | Lógica del CRUD de comisiones. |
| `section_years.py` | Lógica del CRUD de cursos lectivos. |
| `professor_section_years.py` | Lógica de asignaciones de profesores. |
| `projects.py` | Lógica de proyectos: creación, eliminación, listado y reglas de visibilidad según privacidad. |

## `tests/`

| Archivo | Qué cubre |
|---|---|
| `conftest.py` | BD temporal de test, limpieza entre tests, mails interceptados y fixtures compartidas (`client`, `login`, `make_professor`). |
| `helpers.py` | Constantes del seed y utilidades para leer códigos y cookies. |
| `test_auth.py` | Login, refresh, logout, perfil y contraseña por código. |
| `test_users.py` | Edición de datos propios y listado de usuarios. |
| `test_students.py` | Alta individual y masiva, y modificación de alumnos. |
| `test_professors.py` | Alta y modificación de profesores. |
| `test_sections.py` | CRUD de comisiones. |
| `test_section_years.py` | CRUD de cursos lectivos. |
| `test_professor_section_years.py` | CRUD de asignaciones de profesores. |
| `test_projects.py` | Proyectos: permisos, creación, listado, visibilidad y eliminación. |

El detalle de cada test está en `tests.md`.

## Cómo agregar un recurso nuevo

1. Definir la tabla en `models/` y exportarla en `models/__init__.py`.
2. Definir los formatos de entrada y salida en `schemas/`.
3. Escribir la lógica y las reglas de negocio en `utils/`.
4. Declarar los endpoints, con permisos y descripción, en `routes/` y exportar el router en `routes/__init__.py`.
5. Registrar el router (y su etiqueta de documentación) en `index.py`.
6. Escribir los tests en `tests/` y documentarlos en `tests.md`.