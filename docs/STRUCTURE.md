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
├── AGENTS.md                     # Reglas para IA y colaboradores
├── opencode.json                 # Configuración (carga docs/ como contexto)
├── docs/
│   ├── commands.md               # Comandos de Docker de uso diario
│   ├── PROJECT.md                    # Idea y alcance del proyecto
│   ├── STRUCTURE.md                  # Este archivo
│   ├── TEMPLATES.md
│   ├── tests.md                      # Documentación de los tests
│   └── WORKFLOW.md
│
├── config/                       # Configuración de la app
│   ├── __init__.py
│   ├── settings.py
│   └── database.py
│
├── data/
│   ├── seed.json                 # Datos de ejemplo (usuarios, comisiones, cursadas, grupos)
│   └── seed_test.json            # Seed mínimo y fijo que usan los tests
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
│   ├── project_status.py
│   ├── student_project.py
│   ├── technology.py
│   ├── project_technology.py
│   ├── image.py
│   ├── status.py
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
│   ├── project.py
│   ├── project_status.py
│   ├── student_project.py
│   ├── me_project.py
│   ├── technology.py
│   ├── image.py
│   ├── status.py
│   └── state/                    # Jerarquía de dominio de estados (sin tabla)
│       ├── __init__.py
│       ├── base.py
│       ├── state_project.py
│       └── state_student_project.py
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
│   ├── projects.py
│   ├── student_projects.py
│   ├── technologies.py
│   ├── images.py
│   ├── project_technologies.py
│   └── statuses.py
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
│   ├── project_statuses.py
│   ├── projects.py
│   ├── student_projects.py
│   ├── technologies.py
│   ├── images.py
│   ├── storage.py
│   ├── project_technologies.py
│   ├── statuses.py
│   └── state/                    # Motor de transiciones y efectos por ámbito
│       ├── __init__.py
│       ├── base.py
│       ├── state_project.py
│       └── state_student_project.py
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
    ├── test_project_statuses.py
    ├── test_project_overview.py
    ├── test_project_insure.py
    ├── test_project_transitions.py
    ├── test_projects.py
    ├── test_student_projects.py
    ├── test_me_project.py
    ├── test_technologies.py
    ├── test_images.py
    ├── test_project_technologies.py
    ├── test_statuses.py
    └── test_seed.py
```

## Cómo se reparten las responsabilidades

Cada recurso sigue el mismo recorrido, de afuera hacia adentro:

`routes/` recibe la request, `schemas/` la valida, `utils/` aplica la lógica y las reglas de negocio, y `models/` define cómo se guarda en la base de datos.

Las rutas son delgadas: declaran el endpoint, sus permisos y su documentación, y delegan en `utils/`. Así la misma lógica se reutiliza desde varias rutas sin repetir código.

## Raíz

| Archivo | Para qué sirve |
|---|---|
| `index.py` | Crea la aplicación FastAPI, configura CORS y la documentación, registra todos los routers, monta `/media` para los archivos de imagen y, al arrancar, crea las tablas y carga el seed. |
| `Dockerfile` | Imagen del backend (Python + dependencias + código). |
| `docker-compose.yml` | Levanta el backend y PostgreSQL, con la BD persistida en un volumen. |
| `requirements.txt` | Dependencias de Python. |
| `pytest.ini` | Configuración de pytest (modo async y alcance del event loop). |
| `.env` | Credenciales y parámetros (base de datos, claves, tiempos, mail). No se versiona. |
| `README.md` | Presentación breve del repositorio. |
| `AGENTS.md` | Reglas y convenciones para IA y colaboradores. |
| `opencode.json` | Configuración del asistente: carga `docs/` como contexto. |

## `docs/`

| Archivo | Para qué sirve |
|---|---|
| `commands.md` | Comandos de Docker de uso diario. |
| `PROJECT.md` | Idea del proyecto, dominio, flujos, permisos y estado. |
| `STRUCTURE.md` | Este archivo: mapa de todo el repositorio. |
| `TEMPLATES.md` | Plantillas de código para recursos nuevos. |
| `tests.md` | Qué verifica cada test. |
| `WORKFLOW.md` | Orden y entregables para trabajar una historia de usuario. |

## `config/`

| Archivo | Para qué sirve |
|---|---|
| `settings.py` | Lee las variables de entorno y las expone como `settings`. |
| `database.py` | Motor async de SQLAlchemy, sesión y la dependencia `db_dependency` que usan las rutas. |

## `data/`

| Archivo | Para qué sirve |
|---|---|
| `seed.json` | Datos de ejemplo realistas (alumnos, profesores, comisiones, cursos lectivos, asignaciones, grupos y miembros), para poder probar sin cargar nada. Solo se carga si la BD está vacía. |
| `seed_test.json` | Seed mínimo y fijo que usan los tests (Ana, Luis y Marta). Así el seed real puede cambiar sin romper los tests. |

## `models/`

| Archivo | Tabla | Contenido |
|---|---|---|
| `user.py` | `users` | Datos comunes de todo usuario y manejo de la contraseña (`set_password`, `verify_password`, `get_mail`). |
| `student.py` | `students` | Datos del alumno (año de ingreso); su mail se calcula por legajo. |
| `professor.py` | `professors` | Datos del profesor (mail propio e indicador de super admin). |
| `section.py` | `sections` | Comisión (por ejemplo `3K1`). |
| `section_year.py` | `section_years` | Curso lectivo: comisión + año, con el mínimo y máximo de estudiantes por grupo. |
| `professor_section_year.py` | `professor_section_years` | Asignación de un profesor a un curso lectivo. |
| `project.py` | `projects` | Proyecto (grupo) de un curso lectivo, con su privacidad (se crea `public`; mientras está `uninsured` se trata como público) y la memoria del subestado asegurado (`id_status_insured`). |
| `project_status.py` | `project_statuses` | Historial de transiciones de estado de un proyecto (estado anterior, nuevo y cuándo ocurrió). |
| `student_project.py` | `student_projects` | Alumnos que integran un proyecto (con `is_leader`, un jefe por grupo como máximo, y `enrolled_at` para la antigüedad). |
| `technology.py` | `technologies` | Tecnología del catálogo (nombre único sin distinguir mayúsculas, descripción opcional e imagen opcional 1 a 1 vía `id_image`). |
| `image.py` | `images` | Archivo de imagen guardado en el almacenamiento (hoy local): `key`, nombre original saneado, content-type (siempre WebP), tamaño, checksum y fecha. |
| `project_technology.py` | `project_technologies` | Vínculo proyecto–tecnología con clave compuesta `(id_project, id_technology)`: se borra con el proyecto (CASCADE) y no permite borrar una tecnología en uso (RESTRICT). |
| `status.py` | `statuses` | Persistencia del catálogo de estados por ámbito (`project`, `student_project`), con `code`, `name`, `description` e `is_final`. |
| `state/base.py` | — | Base `State`: metadatos, transiciones (`next_codes`), efecto `on_enter` y registro `(ambito, code) → clase`. |
| `state/state_project.py` | — | `ProjectState` y sus estados (`Uninsured`, `InIdea`, `InProgress`, `PendingApprovalProject`, `RejectedProject`, `Approved`, `Cancelled`), con transiciones y efectos. |
| `state/state_student_project.py` | — | `StudentProjectState` y sus estados (`Active`, `PendingApprovalMember`, `Abandoned`, `Finished`, `Expelled`, `RejectedMember`), con transiciones y efectos. |
| `token.py` | `refresh_tokens` | Refresh tokens vigentes, guardados hasheados. |
| `email_verification.py` | `email_verifications` | Códigos de verificación por mail (OTP), hasheados. |

## `schemas/`

Definen qué datos acepta y devuelve cada endpoint (altas, modificaciones, respuestas públicas y listados paginados). Hay un archivo por recurso: `auth`, `user`, `student`, `professor`, `section`, `section_year`, `professor_section_year`, `project`, `project_status`, `student_project`, `me_project`, `status`, `technology` e `image`.

## `routes/`

| Archivo | Prefijo | Qué expone |
|---|---|---|
| `auth.py` | `/auth` | Login, refresh, logout y flujo de contraseña por código. |
| `me.py` | `/me` | Datos del usuario logueado, modificación de sus datos personales y consulta de su proyecto (`/me/project`, solo alumnos). |
| `users.py` | `/users` | Listado de usuarios registrados (super admin). |
| `students.py` | `/students` | Alta de alumnos (individual y masiva), su modificación, su eliminación (solo super admin, con la regla de membresías) y listado de alumnos con sus grupos (incluye `is_leader` y el estado de la membresía, filtrable con `status`). |
| `professors.py` | `/professors` | Alta de profesores y su modificación (super admin). |
| `sections.py` | `/sections` | CRUD de comisiones. |
| `section_years.py` | `/section-years` | CRUD de cursos lectivos. |
| `professor_section_years.py` | `/professor-section-years` | CRUD de asignaciones de profesores a cursos lectivos. |
| `projects.py` | `/projects` | Crear (individual y masivo), listar, consultar, modificar, eliminar proyectos, asegurarlos, cambiar su estado (`uninsure`, `start`, `submit`, `approve`, `reject`, `retry`, `cancel`), consultar su historial de estados y su overview (integrantes y responsable). |
| `student_projects.py` | `/projects/{id}/members` | Unirse y abandonar (alumno), aceptar/rechazar y delegar jefatura (jefe), expulsar (profesor del curso lectivo o super admin) y listar integrantes (privilegiados). |
| `technologies.py` | `/technologies` | Alta, edición, consulta y baja de tecnologías (consulta: cualquier usuario; escritura: profesores y super admin), con la imagen en multipart o `id_image` y `PUT`/`DELETE` de la imagen. |
| `images.py` | `/images` | Subida (multipart, profesores y super admin), consulta de datos (cualquier usuario logueado) y borrado de imágenes; el archivo se sirve públicamente en `/media`. |
| `project_technologies.py` | `/projects/{id}/technologies` | Asociar tecnologías a un proyecto (de a una o en lote) y quitarlas (privilegiados, mientras el proyecto no sea final) y listarlas (según la privacidad del proyecto). |
| `statuses.py` | `/statuses` | Consulta de estados por ámbito. |

`routes/__init__.py` reúne todos los routers para que `index.py` los registre.

## `utils/`

| Archivo | Para qué sirve |
|---|---|
| `security.py` | Hash de contraseñas (argon2), tokens JWT y de refresh, y códigos OTP. |
| `auth.py` | Cookie de refresh, búsqueda de usuario por mail, emisión de tokens y la dependencia `user_dependency`. |
| `permissions.py` | Dependencias de rol: `professor_dependency`, `super_admin_dependency` y `student_dependency`. |
| `email.py` | Envío de mails (por consola o por SMTP): código de verificación y bienvenida. |
| `verification.py` | Creación y consumo de códigos OTP (vencimiento, intentos y espera entre pedidos). |
| `seed.py` | Carga inicial desde un archivo JSON (`data/seed.json` por defecto; los tests usan `data/seed_test.json`): usuarios, comisiones, cursos lectivos, asignaciones, grupos y miembros, resolviendo las referencias por claves naturales. |
| `users.py` | Armado de respuestas de usuario, edición de datos propios y listado con filtros. |
| `students.py` | Alta masiva de alumnos, modificación de un alumno, su eliminación (solo super admin; bloqueada con membresías vigentes, limpia restos viejos, sesiones y OTP) y listado con los grupos de cada alumno (filtrado por estado de la membresía). |
| `professors.py` | Alta y modificación de profesores. |
| `sections.py` | Lógica del CRUD de comisiones. |
| `section_years.py` | Lógica del CRUD de cursos lectivos. |
| `professor_section_years.py` | Lógica de asignaciones de profesores, con el listado de los profesores de un curso lectivo (`list_section_year_professors`, usado por el overview de proyectos). |
| `project_statuses.py` | Lógica del historial de estados de un proyecto: registro de transiciones y listado cronológico. |
| `projects.py` | Lógica de proyectos: creación, modificación de atributos, aseguramiento (`insure_project`: jefe, profesor del curso lectivo o super admin; valida `min_students`/`max_students` y rechaza las solicitudes pendientes), transiciones de estado (`uninsure`, `start`, `submit`, `approve`, `reject`, `retry` y `cancel`, solo profesor del curso lectivo o super admin; delega la validación y los efectos en `utils/state/state_project.py`), eliminación, listado y reglas de visibilidad según privacidad (los privilegiados son las membresías `active`/`finished`, el profesor del curso lectivo y el super admin; los `uninsured` se tratan como públicos). |
| `student_projects.py` | Lógica de membresías: unirse, aceptar/rechazar, abandonar, expulsar y delegar jefatura, listar integrantes (paginado y completo), obtener el jefe del grupo (`get_leader`), armar el overview (`build_overview`, también lo usa `GET /me/project`) y las reglas de un solo `member` por alumno; las transiciones y sus efectos (cascada de pendientes, sucesión de jefe por `enrolled_at`) viven en `utils/state/state_student_project.py`. |
| `technologies.py` | Lógica de tecnologías: CRUD, unicidad del nombre sin distinguir mayúsculas (índice sobre `lower(name)` + captura de `IntegrityError`), listado con `q` y paginación, bloqueo de borrado de una tecnología en uso (409) y ciclo de vida de su imagen (subir, reemplazar, quitar). |
| `images.py` | Lógica de imágenes: lectura con límite de tamaño (413), validación de formato y conversión a WebP (EXIF y transparencia), guardado de fila + archivo, borrado con bloqueo si está en uso (409) y respuesta pública con `url`. |
| `storage.py` | Capa de almacenamiento (hoy local): clave única, `url` pública, ruta con chequeo de traversal, escritura atómica y borrado tolerante. Una futura nube solo reemplaza este archivo. |
| `project_technologies.py` | Lógica del vínculo proyecto–tecnología: asociar de a una o en lote (todo o nada con detalle por fila), quitar y listar, con los chequeos de privilegiados, estado final y visibilidad según privacidad (reutiliza `Access` de `utils/projects.py`). |
| `statuses.py` | Lógica de estados: catálogo base derivado de la jerarquía (`DEFAULT_STATUSES`), búsqueda, listado, `to_public`, `membership_initial_status`, `is_member` e `is_insured`. |
| `state/base.py` | Motor `apply_transition`: resuelve el estado actual, valida el destino y ejecuta el efecto de entrada; no hace commit. |
| `state/state_project.py` | Efectos de proyecto (`ProjectEffector`): memoria del subestado al desasegurar y cierre de membresías al aprobar/cancelar. |
| `state/state_student_project.py` | Efectos de membresía (`MembershipEffector`): rechazo de otras solicitudes pendientes y sucesión de jefe (`enrolled_at`). |

## `tests/`

| Archivo | Qué cubre |
|---|---|
| `conftest.py` | BD temporal de test (sembrada una vez por sesión), aislamiento por savepoint entre tests, mails interceptados y fixtures compartidas (`client`, `login`, `make_professor`). |
| `helpers.py` | Constantes del seed y utilidades para leer códigos y cookies. |
| `test_auth.py` | Login, refresh, logout, perfil y contraseña por código. |
| `test_users.py` | Edición de datos propios y listado de usuarios. |
| `test_students.py` | Alta individual y masiva, modificación, listado y eliminación de alumnos (permisos, regla de membresías, legajo libre, sesiones y OTP). |
| `test_professors.py` | Alta y modificación de profesores. |
| `test_sections.py` | CRUD de comisiones. |
| `test_section_years.py` | CRUD de cursos lectivos. |
| `test_professor_section_years.py` | CRUD de asignaciones de profesores. |
| `test_project_statuses.py` | Historial de estados de un proyecto: permisos, registro inicial, orden, paginación y 404. |
| `test_project_overview.py` | Overview de un proyecto: permisos, visibilidad según privacidad, filtro de integrantes por estado, responsables (los profesores del curso lectivo) y jefe (`leader`). |
| `test_project_insure.py` | Aseguramiento de un proyecto: permisos, reglas (memoria del subestado, rango de integrantes), efectos (historial, rechazo de pendientes, privacidad) y 409/404. |
| `test_project_transitions.py` | Transiciones de estado del proyecto (`uninsure`, `start`, `submit`, `approve`, `reject`, `retry`, `cancel`): permisos, transiciones válidas e inválidas, estados finales, memoria del subestado, efectos en las membresías e historial. |
| `test_projects.py` | Proyectos: permisos, creación, listado, visibilidad, modificación y eliminación. |
| `test_student_projects.py` | Integrantes del proyecto: unirse, aceptar/rechazar (jefe), abandonar, expulsar, delegar jefatura, listar y reglas de membresía. |
| `test_me_project.py` | Mi proyecto (`GET /me/project`): permisos, equipo donde el alumno es miembro (overview completo, `restricted` en `false`) y solicitudes de ingreso (`pending_approval`/`rejected`, ordenadas). |
| `test_technologies.py` | Tecnologías: permisos, alta con unicidad case-insensitive, consulta con `q` y paginación, edición (incluye limpiar la descripción), borrado bloqueado en uso (409) e imagen (subida en multipart, `id_image`, `PUT`/`DELETE`, reemplazo que borra la anterior). |
| `test_images.py` | Imágenes: permisos, subida con conversión a WebP y archivo en disco, límites de tamaño (413) y formato (422), saneado del nombre y borrado de fila + archivo. |
| `test_project_technologies.py` | Tecnologías del proyecto: permisos, asociar (individual y en lote todo o nada), regla de estado final, visibilidad según privacidad, quitado y cascada al borrar el proyecto. |
| `test_statuses.py` | Estados: permisos, consulta, filtro por ámbito, paginación y reglas por ámbito (jerarquía `State`: categorías `member` e `insured`, inicial, transiciones, registro y fallback). |
| `test_seed.py` | Carga del seed real: conteos, rangos de estudiantes, asignaciones, grupos, privacidad, estados, jefes de grupo, unicidad y referencias. |

El detalle de cada test está en `docs/tests.md`.

## Cómo agregar un recurso nuevo

1. Definir la tabla en `models/` y exportarla en `models/__init__.py`.
2. Definir los formatos de entrada y salida en `schemas/`.
3. Escribir la lógica y las reglas de negocio en `utils/`.
4. Declarar los endpoints, con permisos y descripción, en `routes/` y exportar el router en `routes/__init__.py`.
5. Registrar el router (y su etiqueta de documentación) en `index.py`.
6. Escribir los tests en `tests/` y documentarlos en `docs/tests.md`.