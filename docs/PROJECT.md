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

Datos comunes: nombre, apellido, legajo y fecha de nacimiento. El **legajo no es único entre tipos** (un alumno y un profesor pueden compartir legajo), pero sí es único **dentro de cada tipo**: no puede repetirse entre alumnos ni entre profesores.

Ambos deben ser **mayores de edad**: al crear o editar la fecha de nacimiento, el usuario debe tener **al menos 18 años** (edad a la fecha del alta), o la operación responde **422**.

Ambos exponen `get_mail()`: el alumno lo calcula y el profesor devuelve su atributo.

### Comisiones y cursos lectivos

- **Comisión (`Section`)**: una división de la carrera, por ejemplo `3K1` o `3K2`. El nombre es único y se guarda en mayúsculas.
- **Curso lectivo (`SectionYear`)**: una comisión en un año concreto (por ejemplo, `3K1` de `2025`). La combinación año + comisión es única. Define además la cantidad mínima y máxima de estudiantes que debe tener cada grupo (`min_students` y `max_students`, entre 1 y 100, con `max_students >= min_students`); se usará más adelante para validar el estado del grupo.
- **Asignación de profesor (`ProfessorSectionYear`)**: qué profesor dicta qué curso lectivo. Es una relación muchos a muchos.

### Proyectos (grupos)

- **Proyecto (`Project`)**: un grupo de un curso lectivo, identificado por un número de grupo único dentro de ese curso lectivo.
  - Campos opcionales, `null` al crearse y completados después: nombre, descripción, objetivo y problemática.
  - **Privacidad**: `public`, `protected` o `private`. Se crea `public`. Mientras el proyecto está en estado `uninsured` (Desasegurado) se **trata siempre como público**, sin importar la privacidad almacenada (la `privacy` que devuelve la API es la **efectiva**: `public`, en ese caso); al pasar a un estado aseguraado vuelve a valer la privacidad guardada.
- **Alumno en proyecto (`StudentProject`)**: relación muchos a muchos entre alumnos y proyectos. Un miembro puede ser el **jefe de grupo** (`is_leader`); hay a lo sumo uno por proyecto. Cada membresía guarda su **fecha de inscripción** (`enrolled_at`), que define la antigüedad y el orden de sucesión de jefe. Un alumno solo puede ser **`member`** (`active` o `finished`) de **un** proyecto en todo el sistema; sus demás membresías deben ser `pending_approval` (a la espera) o no pertenecer (`abandoned`, `expelled`, `rejected`). Al pasar a `member`, sus otras solicitudes `pending_approval` pasan a `rejected`.
- **Tecnología (`Technology`)**: un ítem del catálogo (nombre y descripción opcional) con el que se declara qué tecnologías usa cada proyecto. El nombre es obligatorio (máximo 100 caracteres) y no puede repetirse **sin distinguir mayúsculas** (`React` y `react` son la misma); la descripción es opcional (máximo 500).
- **Tecnología del proyecto (`ProjectTechnology`)**: relación muchos a muchos entre proyectos y tecnologías, con **clave compuesta** `(id_project, id_technology)` (el par existe una sola vez). Cada proyecto tiene su propia lista, aunque compartan catálogo; al eliminar el proyecto, sus vínculos desaparecen con él, y no se puede eliminar una tecnología que algún proyecto esté usando (**409**). La gestión es de los **privilegiados** del proyecto (miembros `active`/`finished`, profesor del curso lectivo y super admin) mientras el proyecto **no esté en un estado final**: asociar de a una (`POST /projects/{id}/technologies`), en lote todo o nada con detalle por fila (`POST /projects/{id}/technologies/bulk`, hasta 100) o quitar (`DELETE /projects/{id}/technologies/{id_technology}`). La consulta (`GET /projects/{id}/technologies`, ordenada por nombre y con filtro `q`) sigue la **privacidad del proyecto**: en `private` solo los privilegiados (**403** al resto); `protected` y `public` (y todo `uninsured`) se ven para cualquiera logueado.

### Estados

- **Estado (`Status`)**: un estado reutilizable identificado por un `ambito` y un `code` (únicos en conjunto), con un `name`, una `description` para mostrar e `is_final` (indica que es terminal: no admite más transiciones). Los ámbitos previstos son `project`, `student_project` y, más adelante, `document`, `idea` y `comment`.
- Cada `Project` y cada `StudentProject` tiene **un estado actual** (relación obligatoria a `Status`). Los proyectos además guardan su historial de transiciones en `project_statuses` (estado anterior, nuevo y cuándo), consultable con `GET /projects/{id}/status-history`; las membresías todavía no tienen historial.
- **Proyectos** (`project`): nacen `uninsured` (Desasegurado). La máquina de estados es: `uninsured → in_idea → in_progress → pending_approval → (approved | rejected)`; `rejected → in_progress`; cualquier estado "insured" puede pasar a `uninsured` o a `cancelled`. `approved` y `cancelled` son **finales**. Cuando un proyecto vuelve de `uninsured` a insured retoma el subestado donde estaba (por ejemplo, `in_progress → uninsured → in_progress`); esa memoria vive en `projects.id_status_insured` (si el grupo nunca estuvo asegurado, va a `in_idea`). La transición inversa `insured → uninsured` es la que escribe esa memoria (`POST /projects/{id}/uninsure`). Cada membresía alumno-proyecto también tiene su estado.
- **Membresías** (`student_project`): el catálogo es `active`, `pending_approval`, `abandoned` (final), `finished` (final), `expelled` (final) y `rejected`. El estado inicial depende de si el grupo ya tiene jefe: si no tiene, el alumno entra `active` (y es el jefe); si ya tiene, queda `pending_approval`.
- **Transiciones** de membresía: el alumno puede volver a enviar una solicitud `rejected` (vuelve a `pending_approval`, implementado en `POST /projects/{id}/members`); el **jefe del grupo** acepta (`pending_approval → active`) o rechaza (`pending_approval → rejected`) con `PATCH /projects/{id}/members/{id_student_project}`. El propio alumno `active` puede abandonar (`active → abandoned`) con `POST .../abandon` y un profesor del curso lectivo o super admin puede expulsar (`active → expelled`) con `POST .../expel`. La transición `active → finished` todavía no tiene endpoint.
- **Reglas por ámbito (jerarquía `State`)**: en código (no en la BD) viven las clases de estado: `State` → `ProjectState` / `StudentProjectState` → estado concreto. Cada clase declara `ambito`, `code`, `name`, `description`, `is_final`, sus transiciones válidas (`next_codes`) y, si aplica, un efecto al entrar (`on_enter`). Las **categorías** se derivan de las clases: `is_member` (`active` + `finished`) da privilegios y es lo que se lista por defecto en `GET /students`; `is_insured` (`in_idea`, `in_progress`, `pending_approval`, `rejected`) marca los estados "asegurados" (el método `is_insured` lo expone la API). `Status` sigue siendo la tabla que persiste el catálogo: la seed puede sumar estados, pero solo los definidos en la jerarquía tienen reglas; un estado desconocido cae en `State`, que no admite transiciones.
- Los estados son **datos**: el catálogo base se carga al arrancar el backend (en código) y la seed puede sumar los suyos. La consulta (`GET /statuses`) sirve para que el frontend arme etiquetas y filtros.
- **Operaciones y estado**: qué se puede hacer según el estado del grupo (los estados se agrupan en desasegurado, insured y finales):

  | Operación | `uninsured` | insured (`in_idea`, `in_progress`, `pending_approval`, `rejected`) | final (`approved`, `cancelled`) |
  |---|---|---|---|
  | Eliminar el grupo (si está vacío) | ✅ | ❌ 409 | ❌ 409 |
  | Editar datos y privacidad | ✅ | ✅ | ❌ 409 |
  | Unirse al grupo | ✅ | ❌ 409 | ❌ 409 |
  | Abandonar el grupo (integrante `active`) | ✅ | ❌ 409 | ❌ 409 |
  | Expulsar a un integrante `active` | ✅ | ❌ 409 | ❌ 409 |
  | Delegar la jefatura a un integrante `active` | ✅ | ✅ | ❌ 409 |
  | Asegurar el grupo | ✅ | ❌ 409 | ❌ 409 |
  | Aceptar o rechazar solicitudes | ✅ | ✅ | ✅ |
  | Asociar o quitar tecnologías del proyecto | ✅ | ✅ | ❌ 409 |

- **Unirse a un grupo** (`POST /projects/{id}/members`): solo el **alumno logueado** se une a sí mismo y solo mientras el proyecto está `uninsured` (si no, **409**). Si el grupo no tiene jefe, entra como jefe y `active`; si ya tiene, queda `pending_approval`. Un proyecto no admite dos jefes. Si el alumno ya es **`member`** (`active`/`finished`) de otro grupo, **no puede enviar solicitudes** para unirse a otros (responde **409**; debe abandonarlo primero), sin importar si el nuevo grupo tiene jefe o no. Si el alumno ya es `member` de otro grupo y este está vacío (sería jefe/`active`), responde **409**. Una solicitud `rejected` solo se puede reenviar si el alumno no es `member` de otro grupo. Al convertirse en `member`, sus otras solicitudes `pending_approval` pasan a `rejected`. Los alumnos con solo solicitudes `pending_approval` en otros grupos sí pueden pedir y el jefe decide.
- **Aceptar o rechazar** (`PATCH /projects/{id}/members/{id_student_project}`): **solo el jefe del grupo**. Acepta (`active`) o rechaza (`rejected`) una membresía `pending_approval`; al aceptar se aplica la regla de un solo `member` (409 si el alumno ya pertenece a otro grupo).
- **Sucesión de jefe**: si el jefe deja el grupo —abandona o es expulsado—, el integrante **`active` más antiguo** (`enrolled_at`) pasa a ser el nuevo jefe. Si no queda ningún `active`, el grupo queda sin jefe.
- **Abandonar** (`POST /projects/{id}/members/{id_student_project}/abandon`): **el propio alumno** abandona su membresía `active`, y solo mientras el proyecto está `uninsured` (si no, **409**).
- **Expulsar** (`POST /projects/{id}/members/{id_student_project}/expel`): **un profesor del curso lectivo o un super admin** expulsa a un integrante `active`, y solo mientras el proyecto está `uninsured` (si no, **409**).
- **Delegar la jefatura** (`POST /projects/{id}/members/{id_student_project}/leader`): **solo el jefe actual**, hacia otro integrante `active` del grupo, mientras el proyecto no esté en un estado final. El jefe saliente sigue en el grupo como `active`.
- **Asegurar el grupo** (`POST /projects/{id}/insure`): **el jefe del grupo, un profesor del curso lectivo o un super admin** sacan al proyecto de `uninsured` y lo pasan a un estado asegurado, confirmando el equipo. Solo desde `uninsured` (si no, **409**); la cantidad de integrantes `active` debe estar entre `min_students` y `max_students` del curso lectivo (si no, **409**). El estado destino es el subestado asegurado recordado (`id_status_insured`) o, si el grupo nunca estuvo asegurado, `in_idea`. Al asegurar, las solicitudes `pending_approval` pasan a `rejected`, el proyecto deja de tratarse como público y **ya no se pueden unir** integrantes nuevos. Se registra en el historial de estados.
- **Transiciones de estado del proyecto** (todas por **un profesor del curso lectivo o un super admin**, ninguna admite un estado final → **409**):
  - `POST /projects/{id}/uninsure`: asegurado (`in_idea`, `in_progress`, `pending_approval` o `rejected`) → `uninsured`. Guarda la memoria del subestado saliente en `id_status_insured`, el proyecto vuelve a tratarse como público y se pueden unir integrantes.
  - `POST /projects/{id}/start`: `in_idea` → `in_progress`.
  - `POST /projects/{id}/submit`: `in_progress` → `pending_approval`.
  - `POST /projects/{id}/approve`: `pending_approval` → `approved` (final); las membresías `active` pasan a `finished` y las `pending_approval` a `rejected`.
  - `POST /projects/{id}/reject`: `pending_approval` → `rejected`.
  - `POST /projects/{id}/retry`: `rejected` → `in_progress`.
  - `POST /projects/{id}/cancel`: cualquier estado no final → `cancelled` (final); las membresías `active` pasan a `abandoned` y las `pending_approval` a `rejected`.


## Flujos principales

### Autenticación

- Login con **mail completo y contraseña**.
- **Access token** JWT de corta duración (15 min), enviado en el header `Authorization: Bearer`.
- **Refresh token** opaco, guardado **hasheado** en la BD y enviado en una cookie `HttpOnly`. Se rota en cada renovación y se invalida al cerrar sesión o cambiar la contraseña.
- Las cuentas se crean **sin contraseña**. El usuario la crea (o la recupera) pidiendo un **código de 6 dígitos por mail** (OTP), que vence a los 10 minutos, se usa una sola vez y se bloquea tras 5 intentos fallidos.

### Alta de usuarios

- Los **alumnos** los crean los profesores (uno por uno o en masa, pensado para cargar un Excel). La carga masiva es todo o nada.
- Los **profesores** los crea un profesor super admin.
- Los usuarios editan sus propios datos personales (nombre, apellido, fecha de nacimiento). Un profesor corrige datos de alumnos y un super admin corrige datos de profesores, incluidos legajo y mail. Al cambiar el mail de un profesor se cierran sus sesiones y se envía un aviso a la dirección vieja y a la nueva.

### Permisos

| Recurso | Consultar | Crear / modificar / eliminar |
|---|---|---|
| Usuarios (listado) | Super admin | n/a |
| Alumnos | Profesores (de sus cursos lectivos) y super admin | Cualquier profesor |
| Profesores | n/a | Super admin |
| Comisiones | Cualquier usuario logueado | Super admin |
| Cursos lectivos | Cualquier usuario logueado | Super admin |
| Asignaciones de profesores | Cualquier usuario logueado | Super admin |
| Proyectos | Cualquier usuario logueado (el detalle depende de la privacidad) | Profesores del curso lectivo, super admin y miembros `active`/`finished` (solo modificar atributos). Asegurar: jefe del grupo, profesor del curso lectivo o super admin |
| Integrantes del proyecto | Privilegiados (miembros `active`/`finished`, profesores del curso lectivo y super admin) | Unirse y abandonar: el propio alumno; aceptar/rechazar y delegar jefatura: el jefe del grupo; expulsar: el profesor del curso lectivo o super admin |
| Tecnologías | Cualquier usuario logueado | Cualquier profesor (incluye super admin) |
| Tecnologías del proyecto | Cualquier usuario logueado (según la privacidad del proyecto; en `private` solo privilegiados) | Privilegiados del proyecto, solo mientras no esté en un estado final |
| Estados | Cualquier usuario logueado | n/a (por ahora se cargan con el backend) |

### Proyectos y privacidad

- Los profesores crean los grupos, individualmente o en masa, y los dejan vacíos. Los alumnos se unirán después.
- Un profesor solo gestiona proyectos de los cursos lectivos a los que está asignado. Un super admin puede gestionar los de cualquiera.
- Los proyectos se crean con privacidad `public`, pero mientras estén `uninsured` se tratan siempre como públicos aunque la privacidad almacenada sea `private` o `protected`; recién en un estado aseguraado aplica la privacidad guardada.
- Los **privilegiados** del proyecto —profesores del curso lectivo, super admin y miembros con membresía `active`/`finished`— pueden modificar sus atributos (`name`, `description`, `objective`, `problem` y `privacy`) mientras no esté en un estado final. Enviar un campo de texto con `null` lo limpia; `privacy` no admite `null`.
- Un proyecto solo se elimina si está en estado **`uninsured`** (Desasegurado) y **sin ningún alumno** (basta una membresía en cualquier estado); si no, responde **409**.
- Visibilidad del detalle. Los **privilegiados** son los miembros del grupo con membresía **`active` o `finished`**, los profesores del curso lectivo y los super admin (una membresía `pending_approval`, `abandoned`, `expelled` o `rejected` no da privilegios):
  - **`uninsured`** (Desasegurado): como público, cualquiera ve todo el detalle.
  - **`public`**: cualquier usuario ve todo el detalle.
  - **`protected`**: los privilegiados ven todo; el resto ve la información básica (el proyecto aparece con `restricted` en `true` y nombre, descripción, objetivo y problemática en `null`). Los datos sensibles (documentación, repositorio de GitHub), cuando existan, se ocultan a quien no sea privilegiado.
  - **`private`**: solo los privilegiados. Para el resto el proyecto no aparece en el listado ni se cuenta en `total`, y consultarlo responde **403**.
- El **overview** (`GET /projects/{id}/overview`) devuelve el proyecto con sus **integrantes**, sus **responsables** —los **profesores asignados a su curso lectivo** (quienes hacen el seguimiento del grupo), sin mail— y su **jefe** (`leader`, el jefe del grupo, o `null` si no tiene; el jefe también queda marcado con `is_leader` en cada integrante), con la misma visibilidad de arriba. Por defecto lista los integrantes `active` y `finished` (categoría `member`); el parámetro repetible `status` (solo privilegiados) permite pedir otros estados; el jefe y los responsables se resuelven aparte del filtro. En un proyecto protegido, quien no es privilegiado igual recibe los integrantes, los responsables y el jefe, además de la información básica.
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
- Proyectos: crear (individual y masivo), listar, consultar, modificar atributos (privilegiados, mientras no sea final) y eliminar (solo si están `uninsured` y vacíos), con visibilidad según privacidad (los `uninsured` se tratan como públicos; se crean `public`).
- Integrantes del proyecto: unirse a un grupo (`POST /projects/{id}/members`, solo alumnos y solo en `uninsured`, el primero es jefe/`active` y el resto `pending_approval`), aceptar o rechazar solicitudes (`PATCH /projects/{id}/members/{id_student_project}`, solo el jefe), abandonar (`POST .../abandon`, el propio alumno y solo en `uninsured`), expulsar (`POST .../expel`, profesor del curso lectivo o super admin y solo en `uninsured`), delegar la jefatura (`POST .../leader`, solo el jefe, en estados no finales) y listar integrantes (`GET /projects/{id}/members`, privilegiados). Sucesión de jefe al `active` más antiguo (`enrolled_at`) al irse el jefe. Regla de un solo `member` (`active`/`finished`) por alumno en todo el sistema, con cascada de `pending_approval` a `rejected`.
- Estados: catálogo base cargado por el backend (proyectos y membresías), estado actual de cada proyecto y membresía, marca de estado final (`is_final`), jefe de grupo (`is_leader`) y consulta `GET /statuses`.
- Estados de proyecto: máquina de estados (`uninsured → in_idea → in_progress → pending_approval → approved | rejected`), categoría `insured` y método `is_insured` en la respuesta de `GET /statuses`.
- Historial de estados de proyecto: tabla `project_statuses` con registro inicial al crear (estado anterior `null` y nuevo `uninsured`) y consulta `GET /projects/{id}/status-history`, con la misma visibilidad que el detalle del proyecto.
- Overview del proyecto (`GET /projects/{id}/overview`): el proyecto con sus integrantes, sus responsables (los profesores de su curso lectivo, sin mail) y su jefe (`leader`), con la misma visibilidad según privacidad, filtro de integrantes por estado (solo privilegiados) y orden con el jefe primero.
- Aseguramiento de proyecto (`POST /projects/{id}/insure`): el jefe del grupo, un profesor del curso lectivo o un super admin pasan el grupo de `uninsured` a un estado asegurado, validando `min_students`/`max_students` y rechazando las solicitudes pendientes; la memoria del subestado (`id_status_insured`) hace que vuelva al subestado anterior (por defecto `in_idea`). A partir de ahí ya no se unen integrantes nuevos.
- Transiciones de estado del proyecto (profesor del curso lectivo o super admin): `POST /projects/{id}/uninsure` (asegurado → `uninsured`, guarda la memoria), `POST .../start` (`in_idea` → `in_progress`), `POST .../submit` (`in_progress` → `pending_approval`), `POST .../approve` (`pending_approval` → `approved`, las membresías `active` pasan a `finished`), `POST .../reject` (`pending_approval` → `rejected`), `POST .../retry` (`rejected` → `in_progress`) y `POST .../cancel` (cualquier no final → `cancelled`, las membresías `active` pasan a `abandoned` y las `pending_approval` a `rejected`). Estados finales no admiten ninguna transición.
- Tecnologías: catálogo con alta, edición, consulta y baja (`/technologies`, profesores y super admin; lectura para cualquier usuario logueado), unicidad del nombre sin distinguir mayúsculas y bloqueo de borrado de una tecnología en uso (409).
- Tecnologías del proyecto: los privilegiados asocian (`POST /projects/{id}/technologies`), en lote todo o nada con detalle por fila (`POST .../bulk`) y quitan (`DELETE .../{id_technology}`) mientras el proyecto no esté en un estado final; la consulta (`GET /projects/{id}/technologies`) sigue la privacidad del proyecto y los vínculos se borran con el proyecto.
- Tests automáticos de todo lo anterior y documentación de los endpoints en `/docs`.

**Pendiente**
- Finalizar la participación de un integrante (`active → finished`): todavía no tiene endpoint.
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