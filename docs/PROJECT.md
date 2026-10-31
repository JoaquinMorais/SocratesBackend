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
- **Curso lectivo (`SectionYear`)**: una comisión en un año concreto (por ejemplo, `3K1` de `2025`). La combinación año + comisión es única. Define la cantidad mínima y máxima de estudiantes por grupo (`min_students` y `max_students`, entre 1 y 100, con `max_students >= min_students`) y `allow_project_joins` (por defecto `false`), que habilita reintentar una cursada `finished_failed` en ese curso. El profesor asignado o un super admin pueden cambiar `allow_project_joins` con `PATCH /section-years/{id}/settings`.
- **Asignación de profesor (`ProfessorSectionYear`)**: qué profesor dicta qué curso lectivo. Es una relación muchos a muchos.
- **Inscripción y cursada del alumno (`StudentSectionYear`)**: cada fila del vínculo alumno + curso lectivo tiene un `state` (`status.code`) y un objeto `status` del ámbito `student_section_year`; `id_status`/`status` es la fuente canónica y `state` queda como espejo para los índices y filtros:
  - `registered` (Anotado): la **inscripción** administrativa; `status` es `registered` (`is_final=true`). Hay **una por alumno y año**. Se crea al dar de alta al alumno con `id_section_year` (individual o masivo) o con `POST /student-section-years`.
  - `attending` (Cursando), `abandoned` (Abandonada), `finished_approved` (Finalizada y aprobada) y `finished_failed` (Finalizada y desaprobada): la **cursada académica**; los estados y sus transiciones viven en `models/state/student_section_year.py` y se aplican con el patrón `State`. Se crea y actualiza automáticamente al integrar un proyecto; no se crea, edita ni elimina desde `/student-section-years` (**409**). Hay una cursada actual (`attending`) por alumno y una fila de cursada por alumno y curso lectivo; la inscripción y la cursada pueden convivir en la misma comisión como dos filas.
  - El **año actual** del alumno es el de su cursada `attending`; si no tiene, el de la última `finished_*`; si no, el de la última inscripción `registered`. Al unirse, aceptar o añadir a un proyecto, el año del proyecto debe coincidir con ese año (si no tiene filas, se permite; si entra como `active`, se crea la cursada): **409** si no coincide. La cursada nace `attending`; abandonar o expulsar la deja `abandoned`; aprobar el proyecto, `finished_approved`; cancelarlo, `finished_failed`. Si el curso tiene `allow_project_joins=true`, un `finished_failed` puede reactivarse a `attending`; un `finished_approved` no.
  - Un curso lectivo con filas no se puede eliminar (**409**). Cambiar su **año** responde **409** solo si alguna inscripción quedaría duplicada en el año nuevo; si se permite, mueve la copia `year` de todas las filas.

### Proyectos (grupos)

- **Proyecto (`Project`)**: un grupo de un curso lectivo, identificado por un número de grupo único dentro de ese curso lectivo. Si no se indica el número al crearlo, se toma el **primer número libre** del curso lectivo; los huecos (por borrados o números elegidos a mano) se reutilizan en las altas automáticas y masivas.
  - Campos opcionales, `null` al crearse y completados después: nombre, descripción, objetivo y problemática.
  - **Privacidad**: `public`, `protected` o `private`. Se crea `public`. Mientras el proyecto está en estado `uninsured` (Desasegurado) se **trata siempre como público**, sin importar la privacidad almacenada (la `privacy` que devuelve la API es la **efectiva**: `public`, en ese caso); al pasar a un estado aseguraado vuelve a valer la privacidad guardada.
- **Alumno en proyecto (`StudentProject`)**: relación muchos a muchos entre alumnos y proyectos. Un miembro puede ser el **jefe de grupo** (`is_leader`); hay a lo sumo uno por proyecto. Cada membresía guarda su **fecha de inscripción** (`enrolled_at`), que define la antigüedad y el orden de sucesión de jefe. Un alumno solo puede ser **`member`** (`active` o `finished`) de **un** proyecto en todo el sistema; sus demás membresías deben ser `pending_approval` (a la espera) o no pertenecer (`abandoned`, `expelled`, `rejected`). Al pasar a `member`, sus otras solicitudes `pending_approval` pasan a `rejected`.
- **Tecnología (`Technology`)**: un ítem del catálogo (nombre y descripción opcional) con el que se declara qué tecnologías usa cada proyecto. El nombre es obligatorio (máximo 100 caracteres) y no puede repetirse **sin distinguir mayúsculas** (`React` y `react` son la misma); la descripción es opcional (máximo 500). Cada tecnología puede tener **a lo sumo una imagen** (relación 1 a 1).
- **Imagen (`Image`)**: archivo subido al sistema (hoy se guarda en disco local, servido en `/media`). Se acepta **jpeg, png o webp** de hasta **5 MB**; siempre se guarda **convertido a WebP** (calidad 85), corrigiendo la orientación EXIF y conservando la transparencia. Se registra el nombre original saneado, el tamaño, el checksum y la fecha; la API devuelve la `url` pública. Reemplazar o quitar la imagen de una tecnología **borra el archivo anterior**; una imagen asignada a una tecnología no se puede eliminar por separado (**409**).
- **Tecnología del proyecto (`ProjectTechnology`)**: relación muchos a muchos entre proyectos y tecnologías, con **clave compuesta** `(id_project, id_technology)` (el par existe una sola vez). Cada proyecto tiene su propia lista, aunque compartan catálogo; al eliminar el proyecto, sus vínculos desaparecen con él, y no se puede eliminar una tecnología que algún proyecto esté usando (**409**). La gestión es de los **privilegiados** del proyecto (miembros `active`/`finished`, profesor del curso lectivo y super admin) mientras el proyecto **no esté en un estado final**: asociar de a una (`POST /projects/{id}/technologies`), en lote todo o nada con detalle por fila (`POST /projects/{id}/technologies/bulk`, hasta 100) o quitar (`DELETE /projects/{id}/technologies/{id_technology}`). La consulta (`GET /projects/{id}/technologies`, ordenada por nombre y con filtro `q`) sigue la **privacidad del proyecto**: en `private` solo los privilegiados (**403** al resto); `protected` y `public` (y todo `uninsured`) se ven para cualquiera logueado.

### Estados

- **Estado (`Status`)**: un estado reutilizable identificado por un `ambito` y un `code` (únicos en conjunto), con un `name`, una `description` para mostrar e `is_final` (indica que es terminal: no admite más transiciones). Los ámbitos actuales son `project`, `student_project` y `student_section_year`; más adelante se sumarán `document`, `idea` y `comment`.
- Cada `Project`, cada `StudentProject` y cada `StudentSectionYear` tiene **un estado actual** (relación obligatoria a `Status`). Los proyectos además guardan su historial de transiciones en `project_statuses` (estado anterior, nuevo y cuándo), consultable con `GET /projects/{id}/status-history`; las membresías y las cursadas todavía no tienen historial.
- **Proyectos** (`project`): nacen `uninsured` (Desasegurado). La máquina de estados es: `uninsured → in_idea → in_progress → pending_approval → (approved | rejected)`; `rejected → in_progress`; cualquier estado "insured" puede pasar a `uninsured` o a `cancelled`. `approved` y `cancelled` son **finales**. Cuando un proyecto vuelve de `uninsured` a insured retoma el subestado donde estaba (por ejemplo, `in_progress → uninsured → in_progress`); esa memoria vive en `projects.id_status_insured` (si el grupo nunca estuvo asegurado, va a `in_idea`). La transición inversa `insured → uninsured` es la que escribe esa memoria (`POST /projects/{id}/uninsure`). Cada membresía alumno-proyecto también tiene su estado.
- **Membresías** (`student_project`): el catálogo es `active`, `pending_approval`, `abandoned` (final), `finished` (final), `expelled` (final) y `rejected`. El estado inicial depende de si el grupo ya tiene jefe: si no tiene, el alumno entra `active` (y es el jefe); si ya tiene, queda `pending_approval`.
- **Cursadas** (`student_section_year`): catálogo `registered` (final), `attending`, `abandoned`, `finished_approved` (final) y `finished_failed`. Transiciones: `attending → abandoned | finished_approved | finished_failed`; `abandoned → attending`; `finished_failed → attending` solo con `allow_project_joins`; `registered` y `finished_approved` no transicionan. La fuente canónica es `id_status`/`status`; `state` queda como espejo para índices y filtros.
- **Transiciones** de membresía: el alumno puede volver a enviar una solicitud `rejected` (vuelve a `pending_approval`, implementado en `POST /projects/{id}/members`); el **jefe del grupo** acepta (`pending_approval → active`) o rechaza (`pending_approval → rejected`) con `PATCH /projects/{id}/members/{id_student_project}`. El propio alumno `active` puede abandonar (`active → abandoned`) con `POST .../abandon` y un profesor del curso lectivo o super admin puede expulsar (`active → expelled`) con `POST .../expel`. La transición `active → finished` todavía no tiene endpoint.
- **Reglas por ámbito (jerarquía `State`)**: en código (no en la BD) viven las clases de estado: `State` → `ProjectState` / `StudentProjectState` / `StudentSectionYearState` → estado concreto. Cada clase declara `ambito`, `code`, `name`, `description`, `is_final`, sus transiciones válidas (`next_codes`) y, si aplica, un efecto al entrar (`on_enter`). Las **categorías** se derivan de las clases: `is_member` (`active` + `finished`) da privilegios y es lo que se lista por defecto en `GET /students`; `is_insured` (`in_idea`, `in_progress`, `pending_approval`, `rejected`) marca los estados "asegurados" (el método `is_insured` lo expone la API). `Status` sigue siendo la tabla que persiste el catálogo: la seed puede sumar estados, pero solo los definidos en la jerarquía tienen reglas; un estado desconocido cae en `State`, que no admite transiciones.
- Los estados son **datos**: el catálogo base se carga al arrancar el backend (en código) y la seed puede sumar los suyos. La consulta (`GET /statuses`) sirve para que el frontend arme etiquetas y filtros.
- **Operaciones y estado**: qué se puede hacer según el estado del grupo (los estados se agrupan en desasegurado, insured y finales):

  | Operación | `uninsured` | insured (`in_idea`, `in_progress`, `pending_approval`, `rejected`) | final (`approved`, `cancelled`) |
  |---|---|---|---|
  | Eliminar el grupo (si está vacío) | ✅ | ❌ 409 | ❌ 409 |
  | Editar datos y privacidad | ✅ | ✅ | ❌ 409 |
  | Unirse al grupo | ✅ | ❌ 409 | ❌ 409 |
  | Abandonar el grupo (integrante `active`) | ✅ | ❌ 409 | ❌ 409 |
  | Expulsar a un integrante `active` | ✅ | ❌ 409 | ❌ 409 |
  | Añadir un integrante (profesor del curso lectivo o super admin) | ✅ | ❌ 409 | ❌ 409 |
  | Delegar la jefatura a un integrante `active` | ✅ | ✅ | ❌ 409 |
  | Asegurar el grupo | ✅ | ❌ 409 | ❌ 409 |
  | Aceptar o rechazar solicitudes | ✅ | ✅ | ✅ |
  | Asociar o quitar tecnologías del proyecto | ✅ | ✅ | ❌ 409 |

- **Unirse a un grupo** (`POST /projects/{id}/members`): solo el **alumno logueado** se une a sí mismo y solo mientras el proyecto está `uninsured` (si no, **409**). El proyecto debe ser del año actual del alumno (**409** si no). Si el grupo no tiene jefe, entra como jefe y `active`; si ya tiene, queda `pending_approval`. Si entra como `active`, se crea o reactiva su cursada `attending` de ese curso lectivo; una solicitud `pending_approval` no crea cursada. Un proyecto no admite dos jefes. Si el alumno ya es **`member`** (`active`/`finished`) de otro grupo, **no puede enviar solicitudes** para unirse a otros (responde **409**; debe abandonarlo primero), sin importar si el nuevo grupo tiene jefe o no. Si el alumno ya es `member` de otro grupo y este está vacío (sería jefe/`active`), responde **409**. Una solicitud `rejected` solo se puede reenviar si el alumno no es `member` de otro grupo. Al convertirse en `member`, sus otras solicitudes `pending_approval` pasan a `rejected`. Los alumnos con solo solicitudes `pending_approval` en otros grupos sí pueden pedir y el jefe decide.
- **Aceptar o rechazar** (`PATCH /projects/{id}/members/{id_student_project}`): **solo el jefe del grupo**. Acepta (`active`) o rechaza (`rejected`) una membresía `pending_approval`; al aceptar se aplica la regla de un solo `member` (409 si el alumno ya pertenece a otro grupo), se valida el año actual y se crea la cursada `attending`.
- **Sucesión de jefe**: si el jefe deja el grupo —abandona o es expulsado—, el integrante **`active` más antiguo** (`enrolled_at`) pasa a ser el nuevo jefe. Si no queda ningún `active`, el grupo queda sin jefe.
- **Abandonar** (`POST /projects/{id}/members/{id_student_project}/abandon`): **el propio alumno** abandona su membresía `active`, y solo mientras el proyecto está `uninsured` (si no, **409**). Su cursada de ese curso lectivo pasa a `abandoned`; si se une a otro grupo de la misma comisión, se reactiva esa misma fila.
- **Expulsar** (`POST /projects/{id}/members/{id_student_project}/expel`): **un profesor del curso lectivo o un super admin** expulsa a un integrante `active`, y solo mientras el proyecto está `uninsured` (si no, **409**). Su cursada de ese curso lectivo pasa a `abandoned`.
- **Añadir** (`POST /projects/{id}/members/{id_student}`): **un profesor del curso lectivo o un super admin** añade un alumno al grupo; entra siempre como `active` (y como jefe si el grupo no tenía uno), solo mientras el proyecto está `uninsured` (si no, **409**). Aplica la regla de un solo `member`, valida el año actual, rechaza las otras solicitudes `pending_approval` del alumno y crea la cursada `attending`.
- **Delegar la jefatura** (`POST /projects/{id}/members/{id_student_project}/leader`): **solo el jefe actual**, hacia otro integrante `active` del grupo, mientras el proyecto no esté en un estado final. El jefe saliente sigue en el grupo como `active`.
- **Asegurar el grupo** (`POST /projects/{id}/insure`): **el jefe del grupo, un profesor del curso lectivo o un super admin** sacan al proyecto de `uninsured` y lo pasan a un estado asegurado, confirmando el equipo. Solo desde `uninsured` (si no, **409**); la cantidad de integrantes `active` debe estar entre `min_students` y `max_students` del curso lectivo (si no, **409**). El estado destino es el subestado asegurado recordado (`id_status_insured`) o, si el grupo nunca estuvo asegurado, `in_idea`. Al asegurar, las solicitudes `pending_approval` pasan a `rejected`, el proyecto deja de tratarse como público y **ya no se pueden unir** integrantes nuevos. Se registra en el historial de estados.
- **Transiciones de estado del proyecto** (todas por **un profesor del curso lectivo o un super admin**, ninguna admite un estado final → **409**):
  - `POST /projects/{id}/uninsure`: asegurado (`in_idea`, `in_progress`, `pending_approval` o `rejected`) → `uninsured`. Guarda la memoria del subestado saliente en `id_status_insured`, el proyecto vuelve a tratarse como público y se pueden unir integrantes.
  - `POST /projects/{id}/start`: `in_idea` → `in_progress`.
  - `POST /projects/{id}/submit`: `in_progress` → `pending_approval`.
  - `POST /projects/{id}/approve`: `pending_approval` → `approved` (final); las membresías `active` pasan a `finished`, las `pending_approval` a `rejected` y las cursadas `attending` del proyecto a `finished_approved`.
  - `POST /projects/{id}/reject`: `pending_approval` → `rejected`.
  - `POST /projects/{id}/retry`: `rejected` → `in_progress`.
  - `POST /projects/{id}/cancel`: cualquier estado no final → `cancelled` (final); las membresías `active` pasan a `abandoned`, las `pending_approval` a `rejected` y las cursadas `attending` del proyecto a `finished_failed`.


### Calendario

- **Calendario (`Calendar`)**: relación **1 a 1** con el curso lectivo (`calendars.id_section_year` es único). Nace con el curso lectivo y guarda su `timezone` (informativo: las horas son hora local). Al eliminar el curso lectivo se borran el calendario y sus clases.
- **Clase (`CalendarClass`)**: una fila por **fecha concreta**, no una regla semanal. Campos: fecha, hora de inicio y fin, **modalidad** (`in_person` o `virtual`), título, aula (`location`) y link de la videollamada (`meeting_url`) opcionales. El día de la semana se deriva de la fecha.
  - Sin solapamientos dentro del calendario (**409**) y fechas dentro del año del curso lectivo.
  - **Alta puntual** (`POST /section-years/{id}/calendar-classes`) y **alta en lote** rellenando un patrón: `weekdays` + `from_date`/`to_date` + horario (por ejemplo, todos los martes y miércoles de marzo a noviembre). Es todo o nada: si alguna fecha ya tiene una clase que se superpone, **409**.
  - **Modificación y borrado** de a una (`/calendar-classes/{id}`) o en lote (por `ids` o por filtro de días/fechas). Un **feriado o una suspensión** se maneja editando o borrando las clases de ese día; no hay tabla de feriados ni de excepciones.
  - Gestión: **profesor asignado al curso lectivo** y **super admin**. Consulta: super admin, profesores del curso y **alumnos del curso** (con cursada `attending`/`finished_*` o con un grupo en ese curso lectivo). La inscripción `registered` sola no alcanza.
  - `GET /section-years/{id}/calendar?from&to` devuelve el calendario con sus clases y actividades ordenadas; el rango es opcional (máximo 366 días).
- **Actividad (`Activity`)**: una **entrega** del curso lectivo completo (no se distingue por grupo), con `title` obligatorio, `description` opcional, `due_date` y `due_time` opcional. La fecha debe caer en el año del curso lectivo.
  - CRUD (`/section-years/{id}/activities` y `/activities/{id}`): la gestionan el profesor asignado y el super admin; las ven los alumnos con cursada `attending`/`finished_*` o con un grupo en el curso lectivo (la inscripción `registered` sola no alcanza).
  - `GET /me/calendar?from&to` devuelve **mi calendario** (`section_years`, `classes`, `activities`) de los cursos lectivos del **año actual** del usuario (profesor: sus asignaciones; alumno: su cursada `attending`; si no tiene, la última `finished_*`; si no, la última inscripción `registered`; si no tiene filas, el de su grupo actual), ordenado por fecha y hora.
  - **Carga en lote**: `POST /section-years/{id}/calendar/bulk` recibe `{classes, activities}` (el JSON que arma el frontend desde un Excel), con hasta 1.000 clases y 200 actividades. Es un **append** todo o nada: valida fechas del año, horarios y solapamientos internos (**422**) y contra lo existente (**409**) con detalle `{kind, row, detail}`. `dry_run=true` valida sin escribir y devuelve los conteos.
- **Entrega de proyecto (`Delivery`)**: relación **1 a 1** entre un proyecto y una actividad del mismo curso lectivo. Cada proyecto tiene una entrega por cada actividad, aunque todavía no haya enviado nada.
  - Campos: `link` opcional (URL `http`/`https`), `activity_grade` y `development_grade` opcionales (1 a 100), `submitted_at` y `updated_at` (null hasta el envío/modificación).
  - Las entregas se **pre-crean** para todas las combinaciones proyecto × actividad del mismo curso lectivo al crear proyectos/actividades (individual o en lote) y en el seed.
  - Al cargar el primer link se registra `submitted_at`; cada modificación actualiza `updated_at`. Las notas se pueden cargar sin link.
  - Los integrantes `active`/`finished` pueden enviar o corregir el link mientras el proyecto no sea final; solo el profesor del curso o un super admin cargan las notas y pueden corregir todo, incluso con proyecto final.
  - La entrega, el link y las notas solo las ven los integrantes `active`/`finished`, el profesor del curso y el super admin.
  - Borrar una actividad, un proyecto o un curso lectivo con entregas que tengan link o notas responde **409**; las filas vacías se limpian con el recurso.
  - Estado y comentarios de la entrega quedan para una etapa posterior.
- **Asistencia (`Attendance`)**: una fila por alumno y clase a la que asistió (tabla intermedia entre la cursada y la clase). Solo se guardan los **presentes**: la ausencia es la falta de fila. El método indica `code` (el alumno ingresó el código), `manual` (lo marcó el profesor) o `transcript` (se importó desde el chat de la clase).
  - **Toma (`AttendanceSession`)**: una por clase. El profesor la habilita o reabre y se genera un **código de 6 dígitos** que vence a los `ATTENDANCE_CODE_MINUTES` minutos (10 por defecto); se guarda hasheado y solo se muestra al abrirlo. Reabrir rota el código; cerrar corta los check-ins (las marcas manuales siguen disponibles).
  - El alumno marca con el código solo si tiene una cursada **`attending`** en ese curso lectivo (una inscripción `registered` no alcanza); si la toma está cerrada o vencida **409**, código inválido **422**, y repetir es **idempotente**. La lista de la clase incluye las cursadas `attending` y `finished_approved`/`finished_failed` (con su `state`), pero no las inscripciones ni las abandonadas; es solo para el profesor/super admin, y el alumno consulta su historial en `GET /me/attendance`. El marcado manual individual, en lote y la importación solo aceptan cursadas `attending`; una cursada `finished_*` se puede consultar y desmarcar, pero no marcar de nuevo.
  - **Importación desde el chat**: el profesor sube un archivo de texto/CSV o pega el chat en `POST /calendar-classes/{id}/attendance/import-transcript` (y `.../text`). Se buscan mensajes `LEGAJO-ApellidoNombre`: el **legajo debe ser exacto**; el nombre tolera tildes, errores, orden invertido y nombres faltantes (umbral `ATTENDANCE_NAME_SIMILARITY`, 0.75). Es en dos pasos (`dry_run` por defecto): primero un reporte y luego la confirmación. Las filas quedan `method: transcript`, no se pisa una asistencia existente y no se guarda el archivo. Solo se consideran alumnos con cursada `attending`; funciona en cualquier modalidad.
  - **Marcado manual en lote**: `POST /calendar-classes/{id}/attendance/bulk` recibe `id_students` (1 a 200), resuelve la cursada `attending` de cada alumno en el curso lectivo y los marca presentes (`method: manual`). Es **todo o nada** (si algún alumno no existe o no está cursando, 422 con detalle por fila), **idempotente** y funciona con la toma cerrada.
  - **Porcentaje de asistencia**: cada cursada expone `attended_classes`, `total_classes` y `attendance_percentage` (0-100, dos decimales; `null` si no hay clases con toma). El denominador son las clases con `AttendanceSession` del curso lectivo; si se consulta con `from`/`to`, solo las del rango. Se calcula por `id_student_section_year`, así que dos cursadas del mismo alumno nunca se mezclan.
  - **Asistencia del proyecto**: `GET /projects/{id}/attendance` (profesor del curso lectivo o super admin) devuelve los integrantes `active`/`finished` por defecto, con `status` opcional, rango opcional y su porcentaje de asistencia en el curso lectivo del proyecto. La asistencia propia se consulta en `GET /me/attendance`, que además devuelve un resumen por curso lectivo.

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
| Usuarios (listado y baja) | Super admin | Eliminar: super admin (solo altas erróneas; aplica la regla de alumnos o profesores) |
| Alumnos | Profesores (de sus cursos lectivos) y super admin | Crear: cualquier profesor. Modificar: cualquier profesor. Eliminar: solo super admin (solo altas erróneas) |
| Profesores | n/a | Crear, modificar y eliminar: super admin |
| Comisiones | Cualquier usuario logueado | Super admin |
| Cursos lectivos | Cualquier usuario logueado | Super admin; `allow_project_joins`: profesor asignado y super admin |
| Asignaciones de profesores | Cualquier usuario logueado | Super admin |
| Inscripciones y cursadas de alumnos | Profesores y super admin | Inscripciones: super admin; cursadas: automáticas al integrar un proyecto |
| Mi curso lectivo actual (`/me/section-year`) | El propio usuario (profesor o alumno) | n/a (solo lectura) |
| Proyectos | Cualquier usuario logueado (el detalle depende de la privacidad) | Profesores del curso lectivo, super admin y miembros `active`/`finished` (solo modificar atributos). Asegurar: jefe del grupo, profesor del curso lectivo o super admin |
| Integrantes del proyecto | Privilegiados (miembros `active`/`finished`, profesores del curso lectivo y super admin) | Unirse y abandonar: el propio alumno; aceptar/rechazar y delegar jefatura: el jefe del grupo; expulsar y añadir: el profesor del curso lectivo o super admin |
| Tecnologías | Cualquier usuario logueado | Cualquier profesor (incluye super admin) |
| Imágenes | Cualquier usuario logueado (datos) y público (el archivo en `/media`) | Cualquier profesor (incluye super admin) |
| Imagen de una tecnología | Cualquier usuario logueado (viene con la tecnología) | Cualquier profesor (incluye super admin) |
| Tecnologías del proyecto | Cualquier usuario logueado (según la privacidad del proyecto; en `private` solo privilegiados) | Privilegiados del proyecto, solo mientras no esté en un estado final |
| Estados | Cualquier usuario logueado | n/a (por ahora se cargan con el backend) |
| Calendario del curso lectivo | Alumnos con cursada `attending`/`finished_*` o grupo, profesores asignados y super admin | Profesor del curso lectivo y super admin |
| Actividades del curso lectivo | Alumnos con cursada `attending`/`finished_*` o grupo, profesores asignados y super admin | Profesor del curso lectivo y super admin |
| Entregas de proyecto | Integrantes `active`/`finished`, profesor del curso y super admin | Link: integrantes y staff; notas: profesor asignado o super admin; consulta de la actividad: solo staff |
| Asistencia de una clase | Profesor del curso lectivo y super admin | Profesor del curso lectivo y super admin |
| Asistencia de los integrantes de un proyecto | Profesor del curso lectivo y super admin | n/a (solo lectura) |
| Marcar mi asistencia (check-in) | El alumno con cursada `attending` en el curso lectivo | n/a |
| Importar asistencia desde el chat | Profesor del curso lectivo y super admin | Profesor del curso lectivo y super admin |
| Mi asistencia (`/me/attendance`) | El propio alumno | n/a (solo lectura) |
| Mi calendario (`/me/calendar`) | El propio usuario (profesor o alumno) | n/a (solo lectura) |
| Mi proyecto (`/me/project`) | El propio alumno (solo alumnos) | n/a (solo lectura) |

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
- El **listado** (`GET /projects`) filtra por curso lectivo, año, comisión, privacidad efectiva y `q` (texto dentro del nombre del proyecto, sin distinguir mayúsculas). Los proyectos sin nombre no coinciden con `q`.
- El **overview** (`GET /projects/{id}/overview`) devuelve el proyecto con sus **integrantes**, sus **responsables** —los **profesores asignados a su curso lectivo** (quienes hacen el seguimiento del grupo), sin mail— y su **jefe** (`leader`, el jefe del grupo, o `null` si no tiene; el jefe también queda marcado con `is_leader` en cada integrante), con la misma visibilidad de arriba. Por defecto lista los integrantes `active` y `finished` (categoría `member`); el parámetro repetible `status` (solo privilegiados) permite pedir otros estados; el jefe y los responsables se resuelven aparte del filtro. En un proyecto protegido, quien no es privilegiado igual recibe los integrantes, los responsables y el jefe, además de la información básica.
- **Mi proyecto** (`GET /me/project`, solo alumnos): el alumno logueado ve su **equipo**, el grupo donde es miembro (`active`/`finished`), con el overview completo del punto anterior, y sus **solicitudes de ingreso** (`pending_approval` y `rejected`, pendientes primero y de la más nueva a la más vieja) con el resumen de cada grupo. Sin equipo ni solicitudes recibe `{"project": null, "requests": []}`. Las solicitudes se ven aunque tenga equipo (por ejemplo, un rechazo anterior); `abandoned`, `expelled`, `active` y `finished` no cuentan como solicitudes.
- `GET /students` devuelve, por cada alumno, sus grupos con el `status` de la membresía. Por defecto solo lista `active` y `finished`; el parámetro repetible `status` permite pedir cualquier combinación de estados (uno desconocido responde **422**). Los grupos se ordenan por estado (`active`, `pending_approval`, `finished`, `abandoned`, `expelled`, `rejected`) y, dentro de cada uno, del curso más reciente al más viejo. Al filtrar por curso/año/comisión solo cuentan las membresías en los estados pedidos; sin esos filtros, los alumnos sin grupo siguen apareciendo. El parámetro `q` busca por nombre, apellido, legajo (exacto) o nombre de sus proyectos (en los estados y el alcance filtrados).

## Estado actual

**Hecho**
- Base de datos, Docker y seed realista con 200 alumnos, 4 comisiones, 10 cursos lectivos (2024-2026; `3K4` solo en 2024), 32 proyectos con estados variados e historial, entregas pre-creadas, 20 tecnologías, actividades, calendarios con feriados y asistencias históricas.
- Login, refresh, logout y flujo de contraseña por código (OTP).
- Alta de alumnos (individual y masiva) y de profesores. Cada alumno puede indicar en qué curso lectivo cursa (`id_section_year` en `POST /students` o por fila en `/students/bulk`), lo que crea su **inscripción** (`registered`); la cursada se crea al integrar un proyecto.
- Eliminación de un alumno (`DELETE /students/{id}`, solo super admin): pensada para altas erróneas; bloqueada si tiene alguna membresía `active`, `finished` o `pending_approval`, con solo restos viejos (`abandoned`, `expelled`, `rejected`) esos vínculos se borran con él; borra también sus inscripciones y cursadas, libera el legajo y cierra sus sesiones y códigos pendientes.
- Eliminación de un profesor (`DELETE /professors/{id}`, solo super admin): pensada para altas erróneas; bloqueada si es super admin o está asignado a un curso lectivo (**409**); libera su mail y su legajo, y cierra sus sesiones y códigos pendientes.
- Eliminación de un usuario (`DELETE /users/{id}`, solo super admin): pensada para altas erróneas y aplica la regla del rol, sea alumno o profesor. También existen `DELETE /students/{id}` y `DELETE /professors/{id}` con el mismo comportamiento.
- Consulta de alumnos registrados con sus grupos (`GET /students`), filtrable por estado de la membresía, curso lectivo, año, comisión y búsqueda por nombre/apellido/legajo o nombre de proyecto.
- Edición de datos propios y de otros usuarios; listado de usuarios.
- CRUD de comisiones y de cursos lectivos (un curso lectivo con profesores asignados, inscripciones/cursadas de alumnos o proyectos no se puede eliminar: **409**).
- Inscripciones y cursadas de alumnos (`/student-section-years`): alta, consulta, edición y baja de la **inscripción** (lectura: profesores y super admin; escritura: super admin; una por alumno y año). La lista muestra también las cursadas con su `state`, su `status` y su `attendance` (porcentaje por curso lectivo) y se puede filtrar por estado; las cursadas se crean y actualizan automáticamente por la membresía al proyecto y no se editan ni borran por esta vía (**409**). No expone datos privados del alumno.
- Cursos lectivos: además del CRUD, `allow_project_joins` (por defecto `false`) permite al profesor asignado o al super admin habilitar el reintento de una cursada `finished_failed` con `PATCH /section-years/{id}/settings`; un `finished_approved` no se puede reintentar.
- Asignación de profesores a cursos lectivos (CRUD).
- Proyectos: crear (individual y masivo), listar (con búsqueda `q` por nombre), consultar, modificar atributos (privilegiados, mientras no sea final) y eliminar (solo si están `uninsured` y vacíos), con visibilidad según privacidad (los `uninsured` se tratan como públicos; se crean `public`).
- Integrantes del proyecto: unirse a un grupo (`POST /projects/{id}/members`, solo alumnos y solo en `uninsured`, el primero es jefe/`active` y el resto `pending_approval`), aceptar o rechazar solicitudes (`PATCH /projects/{id}/members/{id_student_project}`, solo el jefe), abandonar (`POST .../abandon`, el propio alumno y solo en `uninsured`), expulsar (`POST .../expel`, profesor del curso lectivo o super admin y solo en `uninsured`), añadir (`POST /projects/{id}/members/{id_student}`, profesor del curso lectivo o super admin y solo en `uninsured`, entra como `active` y jefe si el grupo estaba vacío), delegar la jefatura (`POST .../leader`, solo el jefe, en estados no finales) y listar integrantes (`GET /projects/{id}/members`, privilegiados). Sucesión de jefe al `active` más antiguo (`enrolled_at`) al irse el jefe. Regla de un solo `member` (`active`/`finished`) por alumno en todo el sistema, con cascada de `pending_approval` a `rejected`.
- Estados: catálogo base cargado por el backend (proyectos y membresías), estado actual de cada proyecto y membresía, marca de estado final (`is_final`), jefe de grupo (`is_leader`) y consulta `GET /statuses`.
- Estados de proyecto: máquina de estados (`uninsured → in_idea → in_progress → pending_approval → approved | rejected`), categoría `insured` y método `is_insured` en la respuesta de `GET /statuses`.
- Historial de estados de proyecto: tabla `project_statuses` con registro inicial al crear (estado anterior `null` y nuevo `uninsured`) y consulta `GET /projects/{id}/status-history`, con la misma visibilidad que el detalle del proyecto.
- Overview del proyecto (`GET /projects/{id}/overview`): el proyecto con sus integrantes, sus responsables (los profesores de su curso lectivo, sin mail) y su jefe (`leader`), con la misma visibilidad según privacidad, filtro de integrantes por estado (solo privilegiados) y orden con el jefe primero.
- Mi proyecto (`GET /me/project`, solo alumnos): el grupo donde el alumno es miembro (`active`/`finished`) con el overview completo, y sus solicitudes de ingreso (`pending_approval` y `rejected`, pendientes primero y de la más nueva a la más vieja).
- Mi curso lectivo actual (`GET /me/section-year`, profesor o alumno): el o los cursos lectivos del **año actual** del usuario. Un profesor usa sus asignaciones (puede dictar varias comisiones del mismo año); un alumno usa su cursada `attending`; si no tiene, la última `finished_*`; si no, la última inscripción `registered`; si no tiene filas, el curso lectivo de su grupo actual (`active`/`finished`). `GET /me/section-year/projects` devuelve todos los proyectos de esos cursos con la privacidad de siempre. `GET /me/calendar` usa el mismo criterio y, si el alumno solo está inscripto, muestra el calendario de esa inscripción; los endpoints directos de calendario/actividades no lo permiten.
- Aseguramiento de proyecto (`POST /projects/{id}/insure`): el jefe del grupo, un profesor del curso lectivo o un super admin pasan el grupo de `uninsured` a un estado asegurado, validando `min_students`/`max_students` y rechazando las solicitudes pendientes; la memoria del subestado (`id_status_insured`) hace que vuelva al subestado anterior (por defecto `in_idea`). A partir de ahí ya no se unen integrantes nuevos.
- Transiciones de estado del proyecto (profesor del curso lectivo o super admin): `POST /projects/{id}/uninsure` (asegurado → `uninsured`, guarda la memoria), `POST .../start` (`in_idea` → `in_progress`), `POST .../submit` (`in_progress` → `pending_approval`), `POST .../approve` (`pending_approval` → `approved`, las membresías `active` pasan a `finished` y las cursadas del proyecto a `finished_approved`), `POST .../reject` (`pending_approval` → `rejected`), `POST .../retry` (`rejected` → `in_progress`) y `POST .../cancel` (cualquier no final → `cancelled`, las membresías `active` pasan a `abandoned`, las `pending_approval` a `rejected` y las cursadas del proyecto a `finished_failed`). Estados finales no admiten ninguna transición.
- Tecnologías: catálogo con alta, edición, consulta y baja (`/technologies`, profesores y super admin; lectura para cualquier usuario logueado), unicidad del nombre sin distinguir mayúsculas y bloqueo de borrado de una tecnología en uso (409). Cada tecnología puede tener una imagen: se sube con el alta o la edición en multipart (`file`), con `PUT /technologies/{id}/image` o vinculando una imagen ya subida (`id_image` en JSON); reemplazarla o quitarla (`DELETE /technologies/{id}/image`) borra el archivo anterior.
- Imágenes: subida (`POST /images`, multipart, profesores y super admin) con conversión a WebP, validación de formato y límite de 5 MB (413); consulta de datos para cualquier usuario logueado; archivo servido públicamente en `/media`. Una imagen asignada a una tecnología no se puede borrar (409).
- Tecnologías del proyecto: los privilegiados asocian (`POST /projects/{id}/technologies`), en lote todo o nada con detalle por fila (`POST .../bulk`) y quitan (`DELETE .../{id_technology}`) mientras el proyecto no esté en un estado final; la consulta (`GET /projects/{id}/technologies`) sigue la privacidad del proyecto y los vínculos se borran con el proyecto.
- Calendario del curso lectivo (`GET /section-years/{id}/calendar`): un calendario 1 a 1 con clases concretas (fecha, horario, modalidad y aula/link). Alta puntual o en lote por patrón de días, modificación y borrado de a una o en lote; un feriado es borrar las clases de ese día. Gestión del profesor del curso y super admin, lectura acotada al curso y sin solapamientos.
- Carga masiva del calendario (`POST /section-years/{id}/calendar/bulk`): clases y actividades desde un JSON (Excel procesado por el frontend), append todo o nada, límites, validación con `dry_run` y detalle de errores por fila.
- Actividades/entregas del curso lectivo (`/section-years/{id}/activities` y `/activities/{id}`): actividades para todo el curso con fecha y hora de entrega opcional; gestión del profesor del curso y super admin, lectura para los alumnos con cursada `attending`/`finished_*` o un grupo en el curso. `GET /me/calendar` devuelve las clases y actividades de los cursos actuales del usuario (año actual).
- Entregas de proyecto por actividad (`/projects/{id}/deliveries` y `/deliveries/{id}`): pre-creadas para cada combinación, con link y dos notas, envío/última modificación, permisos por rol y borrado bloqueado si hay datos.
- Asistencia por clase (`/calendar-classes/{id}/attendance`): el profesor habilita una toma con código de 6 dígitos que vence (o rota), el alumno con cursada `attending` marca con el código, el profesor puede marcar/quitar a mano (de a uno o en lote) solo a alumnos con cursada `attending` y ver la lista con los presentes (`attending`/`finished_*`, con su `state`) y su porcentaje de asistencia. Solo se guardan presentes; `GET /me/attendance` devuelve el historial y el resumen por curso lectivo del alumno; `GET /projects/{id}/attendance` devuelve el mismo resumen para los integrantes del proyecto (profesor del curso o super admin).
- Importación de asistencia desde el chat de la clase (`.txt`/CSV o texto pegado): legajo exacto, nombre tolerante (tildes/errores/nombres faltantes), preview + confirmación, `method: transcript` y reporte detallado por intento.
- Tests automáticos de todo lo anterior y documentación de los endpoints en `/docs`.

**Pendiente**
- Entregas, siguientes etapas: estado y comentarios de la entrega; documentación con archivos.
- Asistencia, siguientes etapas: estados (tarde/justificado), justificaciones, QR/importación desde otros formatos, reportes y límite de intentos para el código.
- Finalizar la participación de un integrante (`active → finished`): todavía no tiene endpoint.
- Idea del proyecto y los campos sensibles (documentación, directorio de GitHub).
- Almacenamiento de imágenes en la nube (S3, Cloudinary...): hoy es local, detrás de una capa de almacenamiento (`utils/storage.py`) para cambiarlo sin tocar la API ni la BD.
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
- **Almacenamiento de archivos detrás de una interfaz**: las imágenes se guardan hoy en disco local (`MEDIA_DIR`) y se sirven en `/media`; una futura nube solo reemplaza `utils/storage.py`.