## Antes de empezar
- `docs/PROJECT.md` y `docs/STRUCTURE.md` ya están cargados como contexto (ver `opencode.json`).
- Antes de crear un recurso nuevo o una tabla intermedia, **leer `docs/TEMPLATES.md`** con la herramienta de lectura.
- Antes de agregar o cambiar tests, **leer `docs/tests.md`**.
- Para cualquier historia de usuario, **seguir `docs/WORKFLOW.md`** (ya está cargado como contexto).
## Protección de archivos sensibles
- NUNCA leas, abras, inspecciones ni muestres el contenido de archivos `.env`.
- NUNCA leas, modifiques, crees, sobrescribas ni elimines archivos `.env`.
- Esta prohibición incluye `.env`, `.env.local`, `.env.development`,
  `.env.production` y cualquier variante similar.
- No ejecutes comandos que impriman su contenido, como `cat .env`,
  `less .env` o `grep` sobre esos archivos.
- Si necesitás conocer las variables de entorno, pedime que te
  proporcione los nombres o valores necesarios manualmente.
- Podés modificar `.env.example` únicamente si es necesario y no contiene secretos reales.


# Guía para IA y colaboradores

Leer esto primero. Es el backend de **Socrates** (FastAPI + SQLModel async + PostgreSQL, en Docker). Para entender qué hace la app y por qué, leer `docs/PROJECT.md`; para ubicar cada archivo, `docs/STRUCTURE.md`; para escribir código nuevo, copiar de `docs/TEMPLATES.md`; para saber qué prueba cada test, `docs/tests.md`.

## Reglas que no se rompen

1. **Todo es asíncrono.** Sesión `AsyncSession` (`db_dependency`), consultas con `await db.exec(...)` y `await db.get(...)`. Nunca código de base de datos síncrono.
2. **Las rutas son delgadas.** La lógica y las reglas de negocio van en `utils/`; las rutas solo declaran endpoint, permisos y documentación.
3. **El punto de entrada es `index.py`** (no `main.py`). Todo router nuevo se registra ahí.
4. **Nunca exponer datos privados:** ni `password_hash` ni fecha de nacimiento fuera de los endpoints propios. El mail de un profesor no se muestra en datos que ven los alumnos.
5. **Nunca subir `.env`** ni credenciales al repo.
6. **No cambiar permisos sin avisar.** La tabla de permisos está en `docs/PROJECT.md`; si cambia, actualizarla.
7. **Todo cambio de comportamiento lleva tests** y se documenta en `docs/tests.md`.

## Idioma y nombres

- Código, identificadores y mensajes de error (`detail`): **inglés**, `snake_case`.
- Documentación para el frontend (`summary`, docstrings, descripciones de `responses`) y los `.md`: **español**.
- Excepción deliberada: `legajo` queda en español (decisión del proyecto).
- Equivalencias del dominio: `Section` = comisión (`3K1`), `SectionYear` = curso lectivo (comisión + año; `allow_project_joins` habilita reintentar `finished_failed`), `StudentSectionYear` = inscripción (`registered`) o cursada (`attending`/`abandoned`/`finished_*`) del alumno + curso lectivo, `Calendar` = calendario 1 a 1 del curso lectivo, `CalendarClass` = clase concreta del calendario, `Activity` = actividad/entrega del curso lectivo, `AttendanceSession` = toma de asistencia de una clase, `Attendance` = asistencia de un alumno a una clase (`code`/`manual`/`transcript`), `Project` = proyecto/grupo.
- Tablas en plural (`section_years`), claves primarias `id_<entidad>` (`id_section_year`), rutas en plural con guiones (`/section-years`).

## Convenciones de código

### Modelos (`models/`)
- Relaciones con `sa_relationship_kwargs={"lazy": "selectin"}`; sin eso, fallan en async.
- Herencia ORM entre tablas **no se usa**: `students` y `professors` tienen como clave el id de `users` (composición).
- **Estados**: son clases de dominio en `models/state/` (sin tabla ni herencia ORM) y sus reglas/efectos viven en `utils/state/`; `Status` es solo la persistencia. Un estado nuevo requiere su clase, sus transiciones (`next_codes`) y su efecto (`on_enter`) si aplica.
- **Tablas intermedias** (muchos a muchos): id propio + `UniqueConstraint` sobre el par.
- Restricciones simples en la BD (`UniqueConstraint`, `CheckConstraint`) y también validadas en el código para dar un error claro.
- Todo modelo nuevo se exporta en `models/__init__.py`.

### Schemas (`schemas/`)
- Un archivo por recurso: `XCreate`, `XUpdate`, `XPublic`, `XList`.
- Los schemas de entrada usan `model_config = ConfigDict(extra="forbid")`: un campo desconocido responde **422**, no se ignora.
- Las normalizaciones (mayúsculas, minúsculas, `strip`) viven en `field_validator`.
- En `XUpdate` todos los campos son opcionales; un body vacío responde **422**.

### Lógica (`utils/`)
- Un archivo por recurso. Funciones: `to_public`, `get_<x>`, `create_<x>`, `update_<x>`, `delete_<x>`, `list_<x>`.
- **Unicidad:** primero se consulta si ya existe (para responder 409 con claro mensaje) y además se captura `IntegrityError` por si dos requests llegan a la vez, haciendo `rollback` y devolviendo 409.
- **Referencias inexistentes** (un id de otro recurso): **404**. El id de un alumno usado como profesor también es 404.
- **Borrado:** se captura `IntegrityError` y se responde **409** ("en uso") si hay datos asociados.
- **Listados:** `limit` (1-100, por defecto 50) y `offset`; respuesta `{items, total, limit, offset}`; orden determinista (siempre con el id como último criterio).
- **Operaciones masivas:** todo o nada, con el detalle de errores por fila.
- Limitación conocida: en un `PATCH`, un campo `null` significa "no enviado"; no se puede borrar un valor con `PATCH`. Si algún día hace falta (por ejemplo, vaciar la descripción de un proyecto), usar `model_fields_set` en lugar de `exclude_none`.

### Rutas (`routes/`)
- `APIRouter(prefix=..., tags=[...])` y export en `routes/__init__.py`.
- Cada endpoint lleva `summary`, una docstring en español que explique quién puede usarlo, las reglas y los campos, y `responses={...}` con todos los códigos de error posibles.
- Los tags nuevos se agregan a `openapi_tags` en `index.py`.
- `PATCH` para modificar, `DELETE` responde 204.

### Permisos (`utils/permissions.py`, `utils/auth.py`)
| Quién | Dependencia |
|---|---|
| Cualquier usuario logueado | `user_dependency` |
| Solo profesores | `professor_dependency` |
| Solo super admin | `super_admin_dependency` |
| Solo alumnos | `student_dependency` |

- Lecturas: normalmente `user_dependency`. Escrituras: super admin o profesor, según el recurso.
- Los permisos que dependen del dato (por ejemplo, "profesor asignado a ese curso lectivo") se resuelven con la clase `Access` de `utils/projects.py`; reutilizar ese patrón.
- Sin login: **401**. Con login pero sin permiso: **403**.

## Autenticación en una línea

Login con mail completo + contraseña → access JWT (15 min, header `Bearer`) + refresh opaco en cookie `HttpOnly` (hasheado en la BD, se rota en cada uso). Las cuentas nuevas no tienen contraseña: la crean con el código por mail (`/auth/password/request` y `/auth/password/confirm`). Detalle en `docs/PROJECT.md`.

## Comandos

```bash
docker compose up --build -d          # primera vez, o si cambia requirements.txt / Dockerfile
docker compose up -d                  # si cambia .env o docker-compose.yml
docker compose exec backend pytest -q # correr todos los tests
# en paralelo, una sesión por sufijo (ver docs/commands.md):
# docker compose run --rm --no-deps -T -e TEST_DB_SUFFIX=historias backend python -m pytest -q
docker compose exec backend pytest tests/test_projects.py -k delete   # algunos tests
docker compose logs -f backend        # logs en vivo
docker compose down -v                # borra la BD (necesario si cambian columnas)
```

- El código `.py` se recarga solo (`--reload`).
- Las tablas se crean con `create_all`, que **no modifica tablas existentes**: si cambias columnas de una tabla que ya existe, hay que hacer `docker compose down -v` (o migrar con Alembic cuando se incorpore).
- Los tests usan una BD temporal por corrida (`<bd>_test_<sufijo>`) que se crea y se borra sola; la BD principal no se toca. Para trabajar con dos sesiones en paralelo, cada una define su `TEST_DB_SUFFIX` (ver `docs/commands.md`).

## Datos del seed (útiles para los tests)

Los tests cargan `data/seed_test.json` (mínimo y fijo); la app, al arrancar con la BD vacía, carga el seed realista `data/seed.json` (comisiones, cursos lectivos, profesores, alumnos, asignaciones, calendarios con sus clases, actividades, grupos, miembros, inscripciones y cursadas de alumnos). Los ids de abajo corresponden a `seed_test.json`.

| Quién | Mail | Contraseña | id |
|---|---|---|---|
| Ana Gómez (alumna) | `100001@sistemas.frc.utn.edu.ar` | `Test1234!` | 1 |
| Luis Pérez (alumno) | `100002@sistemas.frc.utn.edu.ar` | `Test1234!` | 2 |
| Marta Rodríguez (profesora, super admin) | `marta.rodriguez@frc.utn.edu.ar` | `Test1234!` | 3 |

La fixture `make_professor(mail, is_super_admin=False)` crea un profesor común directo en la BD. Los helpers `STUDENT` y `SUPER_ADMIN` están en `tests/helpers.py`.

## Tests

- Un archivo `tests/test_<recurso>.py` por recurso, con secciones en este orden: permisos, crear, consultar, modificar, eliminar.
- Siempre probar: sin login (401), sin permiso (403), caso feliz, duplicado (409), referencia inexistente (404), datos inválidos y campos desconocidos (422).
- Los tests son `async def test_...` sin decoradores; pytest-asyncio está en modo automático.
- Nombres descriptivos en inglés; en `docs/tests.md` se documentan en español con la forma "testear que...".
- Los tests no envían mails: se interceptan en la lista `outbox`.

## Al terminar un cambio

1. Correr todos los tests: deben pasar sin avisos.
2. Actualizar `docs/tests.md` con los tests nuevos.
3. Si cambió el dominio, los permisos o el alcance: actualizar `docs/PROJECT.md`.
4. Si se agregaron o movieron archivos: actualizar `docs/STRUCTURE.md`.
5. Revisar `/docs`: cada endpoint nuevo debe verse con su descripción y errores.

## Pendiente y fuera de alcance por ahora

Ver "Pendiente" en `docs/PROJECT.md`: unirse a un grupo, modificar proyectos, campos sensibles de proyectos, Alembic, cuenta de mail propia y CORS definitivo. No implementar estas piezas sin que se defina primero el comportamiento.