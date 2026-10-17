# Socrates: idea del proyecto

Backend de **Socrates**, un sistema educativo para gestionar usuarios, comisiones y grupos de proyecto de una facultad (UTN FRC). Este repositorio contiene solo el backend; el frontend vive en otro repositorio.

> El alcance todavía no está 100% definido. Este documento describe lo que existe hoy y las decisiones tomadas hasta ahora, y se irá actualizando.

## Stack

- **Python 3.12** con **FastAPI**, usando funciones asíncronas.
- **SQLModel** (sobre SQLAlchemy 2.0 async) con **asyncpg**.
- **PostgreSQL 16**.
- **Docker Compose**: un contenedor para el backend y otro para la base de datos.
- **pytest** para los tests, que corren dentro de Docker con una BD temporal.

## Conceptos del dominio

### Usuarios

Hay dos tipos de usuario, que comparten los datos de `User`:

- **Alumno (`Student`)**: tiene año de ingreso a la carrera. Su mail institucional se calcula como `{legajo}@sistemas.frc.utn.edu.ar`.
- **Profesor (`Professor`)**: tiene un mail propio (puede ser institucional, personal u otro) y un indicador `is_super_admin`.

Datos comunes: nombre, apellido, legajo y fecha de nacimiento. El **legajo no es único** (solo lo es entre alumnos).

Ambos exponen `get_mail()`: el alumno lo calcula y el profesor devuelve su atributo.

### Comisiones y cursos lectivos

- **Comisión (`Section`)**: una división de la carrera, por ejemplo `3K1` o `3K2`. El nombre es único y se guarda en mayúsculas.
- **Curso lectivo (`SectionYear`)**: una comisión en un año concreto (por ejemplo, `3K1` de `2025`). La combinación año + comisión es única. Define además la cantidad mínima y máxima de estudiantes que debe tener cada grupo (`min_students` y `max_students`, entre 1 y 100, con `max_students >= min_students`); se usará más adelante para validar el estado del grupo.
- **Asignación de profesor (`ProfessorSectionYear`)**: qué profesor dicta qué curso lectivo. Es una relación muchos a muchos.

### Proyectos (grupos)

- **Proyecto (`Project`)**: un grupo de un curso lectivo, identificado por un número de grupo único dentro de ese curso lectivo.
  - Campos opcionales, `null` al crearse y completados después: nombre, descripción, objetivo y problemática.
  - **Privacidad**: `public`, `protected` o `private`.
- **Alumno en proyecto (`StudentProject`)**: relación muchos a muchos entre alumnos y proyectos. Un alumno puede recursar y pasar por distintos proyectos en distintos años, pero solo puede estar en uno por curso lectivo. Un miembro puede ser el **jefe de grupo** (`is_leader`); hay a lo sumo uno por proyecto.

### Estados

- **Estado (`Status`)**: un estado reutilizable identificado por un `ambito` y un `code` (únicos en conjunto), con un `name`, una `description` para mostrar e `is_final` (indica que es terminal: no admite más transiciones). Los ámbitos previstos son `project`, `student_project` y, más adelante, `document`, `idea` y `comment`.
- Cada `Project` y cada `StudentProject` tiene **un estado actual** (relación obligatoria a `Status`); por ahora no se guarda historial de cambios.
- **Proyectos** (`project`): nacen `active`; el otro estado es `cancelled` (final).
- **Membresías** (`student_project`): el catálogo es `active`, `pending_approval`, `abandoned` (final), `finished` (final), `expelled` (final) y `rejected`. El estado inicial depende de si el grupo ya tiene jefe: si no tiene, el alumno entra `active`; si ya tiene, queda `pending_approval`.
- **Transiciones** previstas (todavía **sin implementar**): `pending_approval → active | rejected`; `active → abandoned | expelled | finished`; `rejected → pending_approval` (si un profesor habilita o el alumno vuelve a solicitar).
- **Reglas por ámbito (`StatusPolicy`)**: en código (no en la BD) viven, por ámbito, el estado inicial, el orden, las **categorías** y las **transiciones**. Una categoría agrupa códigos: `member` (ámbito `student_project`) es `active` + `finished` y es lo que da privilegios y lo que se lista por defecto en `GET /students`. Los estados de `project` tendrán, cuando se definan, una categoría `insured` ("Asegurado"); todavía no existe.
- Los estados son **datos**: el catálogo base se carga al arrancar el backend (en código) y la seed puede sumar los suyos. La consulta (`GET /statuses`) sirve para que el frontend arme etiquetas y filtros.

## Flujos principales

### Autenticación

- Login con **mail completo y contraseña**.
- **Access token** JWT de corta duración (15 min), enviado en el header `Authorization: Bearer`.
- **Refresh token** opaco, guardado **hasheado** en la BD y enviado en una cookie `HttpOnly`. Se rota en cada renovación y se invalida al cerrar sesión o cambiar la contraseña.
- Las cuentas se crean **sin contraseña**. El usuario la crea (o la recupera) pidiendo un **código de 6 dígitos por mail** (OTP), que vence a los 10 minutos, se usa una sola vez y se bloquea tras 5 intentos fallidos.

### Alta de usuarios

- Los **alumnos** los crean los profesores (uno por uno o en masa, pensado para cargar un Excel). La carga masiva es todo o nada.
- Los **profesores** los crea un profesor super admin.
- Los usuarios editan sus propios datos personales (nombre, apellido, fecha de nacimiento). Un profesor corrige datos de alumnos y un super admin corrige datos de profesores, incluidos legajo y mail.

### Permisos

| Recurso | Consultar | Crear / modificar / eliminar |
|---|---|---|
| Usuarios (listado) | Super admin | n/a |
| Alumnos | Profesores (de sus cursos lectivos) y super admin | Cualquier profesor |
| Profesores | n/a | Super admin |
| Comisiones | Cualquier usuario logueado | Super admin |
| Cursos lectivos | Cualquier usuario logueado | Super admin |
| Asignaciones de profesores | Cualquier usuario logueado | Super admin |
| Proyectos | Cualquier usuario logueado (el detalle depende de la privacidad) | Profesores del curso lectivo y super admin |
| Estados | Cualquier usuario logueado | n/a (por ahora se cargan con el backend) |

### Proyectos y privacidad

- Los profesores crean los grupos, individualmente o en masa, y los dejan vacíos. Los alumnos se unirán después.
- Un profesor solo gestiona proyectos de los cursos lectivos a los que está asignado. Un super admin puede gestionar los de cualquiera.
- Un proyecto solo se elimina si no tiene ningún alumno (basta una membresía en cualquier estado).
- Visibilidad del detalle. Los **privilegiados** son los miembros del grupo con membresía **`active` o `finished`**, los profesores del curso lectivo y los super admin (una membresía `pending_approval`, `abandoned`, `expelled` o `rejected` no da privilegios):
  - **`public`**: cualquier usuario ve todo el detalle.
  - **`protected`**: los privilegiados ven todo; el resto ve la información básica (el proyecto aparece con `restricted` en `true` y nombre, descripción, objetivo y problemática en `null`). Los datos sensibles (documentación, repositorio de GitHub), cuando existan, se ocultan a quien no sea privilegiado.
  - **`private`**: solo los privilegiados. Para el resto el proyecto no aparece en el listado ni se cuenta en `total`, y consultarlo responde **403**.
- `GET /students` devuelve, por cada alumno, sus grupos con el `status` de la membresía. Por defecto solo lista `active` y `finished`; el parámetro repetible `status` permite pedir cualquier combinación de estados (uno desconocido responde **422**). Los grupos se ordenan por estado (`active`, `pending_approval`, `finished`, `abandoned`, `expelled`, `rejected`) y, dentro de cada uno, del curso más reciente al más viejo. Al filtrar por curso/año/comisión solo cuentan las membresías en los estados pedidos; sin esos filtros, los alumnos sin grupo siguen apareciendo.

## Estado actual

**Hecho**
- Base de datos, Docker y seed realista con datos de ejemplo (alumnos, profesores, comisiones, cursadas, asignaciones, grupos y miembros).
- Login, refresh, logout y flujo de contraseña por código (OTP).
- Alta de alumnos (individual y masiva) y de profesores.
- Consulta de alumnos registrados con sus grupos (`GET /students`), filtrable por estado de la membresía, curso lectivo, año o comisión.
- Edición de datos propios y de otros usuarios; listado de usuarios.
- CRUD de comisiones y de cursos lectivos.
- Asignación de profesores a cursos lectivos (CRUD).
- Proyectos: crear (individual y masivo), listar, consultar y eliminar, con visibilidad según privacidad.
- Estados: catálogo base cargado por el backend (proyectos y membresías), estado actual de cada proyecto y membresía, marca de estado final (`is_final`), jefe de grupo (`is_leader`) y consulta `GET /statuses`.
- Tests automáticos de todo lo anterior y documentación de los endpoints en `/docs`.

**Pendiente**
- Unirse a un grupo (alumnos) y modificar los datos de un proyecto.
- Cambiar el estado de un proyecto (incluido cancelado) y de la relación alumno-proyecto (por ejemplo, abandono): endpoints de transición, permisos y validaciones (por ejemplo, el rango `min_students`/`max_students`).
- Idea del proyecto y los campos sensibles (documentación, directorio de GitHub).
- Migraciones con Alembic: hoy las tablas se crean con `create_all`, que no modifica tablas existentes.
- Envío de mails con una cuenta propia del proyecto (hoy se usa una cuenta provisoria).
- Configurar CORS con el origen real del frontend cuando exista.

## Decisiones de diseño

- **Un solo contenedor por servicio**: backend y base de datos separados, con la BD persistida en un volumen.
- **Composición en lugar de herencia de tablas**: `students` y `professors` tienen como clave el id de `users` (relación 1 a 1), porque SQLModel no soporta bien la herencia ORM.
- **Tablas intermedias con id propio** y restricción única sobre el par, para poder modificarlas y sumarles atributos (como el estado) sin rehacerlas.
- **Campos no permitidos responden 422** en vez de ignorarse en silencio.
- **Todo o nada** en las operaciones masivas, con el detalle de errores por fila.
- **Mismo mensaje exista o no el usuario** al pedir un código, para no revelar qué mails están registrados.
- **Mails fuera del request**: se envían en segundo plano y, en desarrollo, pueden redirigirse a una sola dirección o imprimirse en consola.