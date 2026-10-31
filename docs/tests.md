# Tests

Ejecutar (dentro de Docker):

```bash
docker compose exec backend pytest -q
docker compose exec backend pytest -x                              # se detiene en el primer fallo
docker compose exec backend pytest tests/test_auth.py -k refresh   # solo algunos
```

## Cómo funcionan

- Cada corrida crea su **propia** BD temporal (`<nombre_bd>_test_<sufijo>`) y la borra al terminar; la BD principal no se toca. El sufijo sale de `TEST_DB_SUFFIX` (por ejemplo `historias` o `bugs`, uno por sesión de trabajo) o es aleatorio si no se define, así dos suites pueden correr en paralelo sin pisarse. Si una corrida se interrumpe de golpe (SIGKILL), la BD puede quedar: con un sufijo fijo se recicla en la próxima corrida; si no, se limpia con `docker compose down -v`.
- La BD de test se siembra **una sola vez por sesión** (`data/seed_test.json`: Ana, Luis y Marta). Cada test corre dentro de un **savepoint** que se revierte al terminar, así que no se vuelve a truncar ni sembrar entre tests: es rápido y cada test queda aislado.
- La app y los ayudantes de los tests comparten la misma conexión (el `conftest` publica una fábrica de sesiones bindeada a la transacción de test). Por eso se ve todo lo que cada test escribe, pero nada queda entre tests.
- En tests, Argon2 usa parámetros baratos (misma lógica de auth; el hasher de producción no cambia). Esto acelera el seed y los logins.
- Los mails no se envían: quedan en una lista (`outbox`) de donde los tests leen los códigos OTP.
- Las imágenes se guardan en un directorio temporal por sesión (`MEDIA_DIR`); al terminar se borra junto con la BD de test.
- `httpx` llama a la app directamente y conserva las cookies como un navegador.

## Archivos de apoyo

| Archivo | Para qué sirve |
|---|---|
| `tests/conftest.py` | Crea y borra la BD de test, la siembra una vez por sesión, aísla cada test con un savepoint, intercepta los mails y define las fixtures `client`, `login` y `make_professor`. |
| `tests/helpers.py` | Constantes del seed y utilidades: leer el código OTP del mail, leer la cookie de refresh y completar el flujo de contraseña. |

## `tests/test_auth.py`

**Login**
- `test_login_student`: testear que un alumno con contraseña puede loguearse, que el refresh token viaja solo por cookie HttpOnly y no en el JSON.
- `test_login_professor`: testear que un profesor puede loguearse con su mail.
- `test_login_invalid`: testear que se rechaza (401) contraseña incorrecta, legajo inexistente, legajo suelto sin dominio y mail desconocido.

**Perfil (`GET /me`)**
- `test_me_student`: testear que un alumno ve su rol, su mail calculado por legajo, su `birth_date`, `enrollment_year`, `age` y que no se le muestra `is_super_admin`.
- `test_me_super_admin`: testear que Marta figura como profesora y super admin, con `birth_date` y `age`, y sin `enrollment_year`.
- `test_me_requires_valid_token`: testear que sin token o con token inválido responde 401.

**Refresh y logout**
- `test_refresh_rotates_token`: testear que refrescar devuelve un access nuevo y rota la cookie de refresh.
- `test_refresh_rejects_used_token`: testear que un refresh ya usado deja de servir.
- `test_refresh_without_cookie`: testear que refrescar sin cookie responde 401.
- `test_logout_revokes_refresh_token`: testear que tras cerrar sesión el refresh anterior queda inválido.
- `test_logout_without_cookie_is_ok`: testear que cerrar sesión sin cookie no da error.

**Contraseña por código (OTP)**
- `test_password_request_unknown_user_is_silent`: testear que pedir código para un usuario inexistente responde igual (202) y no envía mail.
- `test_password_flow`: testear el flujo completo (pedir código, confirmar, login con la clave nueva; la vieja deja de servir).
- `test_otp_is_single_use`: testear que un código no se puede usar dos veces.
- `test_otp_blocked_after_too_many_attempts`: testear que tras 5 intentos fallidos el código queda bloqueado, incluso el correcto.
- `test_password_too_short`: testear que se rechaza una contraseña de menos de 8 caracteres.
- `test_password_change_closes_sessions`: testear que cambiar la contraseña invalida los refresh tokens existentes.

## `tests/test_users.py`

**Modificar mis datos (`PATCH /me`)**
- `test_update_requires_authentication`: testear que sin login responde 401.
- `test_student_updates_own_data`: testear que un alumno modifica nombre y fecha de nacimiento, que lo no enviado no cambia y que `GET /me` refleja el cambio.
- `test_professor_updates_own_data`: testear que un profesor puede modificar sus datos y conserva su rol de super admin.
- `test_cannot_update_forbidden_fields`: testear que legajo, mail, año de ingreso e `is_super_admin` no se pueden modificar (422).
- `test_update_empty_body_rejected`: testear que un body vacío se rechaza.
- `test_update_invalid_values_rejected`: testear que se rechaza un nombre vacío y una fecha de nacimiento futura.
- `test_cannot_set_under_18_birth_date`: testear que un usuario no puede fijar una fecha de nacimiento que lo deje con menos de 18 años (422).

**Consultar usuarios (`GET /users`)**
- `test_list_requires_authentication`: testear que sin login responde 401.
- `test_student_cannot_list_users`: testear que un alumno no puede listar usuarios (403).
- `test_regular_professor_cannot_list_users`: testear que un profesor que no es super admin no puede listar (403).
- `test_super_admin_lists_users`: testear que un super admin ve todos los usuarios ordenados por apellido.
- `test_list_exposes_only_public_data`: testear que nunca se expone la contraseña, que los alumnos muestran `birth_date`, `age` y `enrollment_year` pero no `is_super_admin`, y los profesores muestran `birth_date` y `age` pero no `enrollment_year`.
- `test_list_filter_by_role`: testear el filtro por rol y que un rol inválido se rechaza.
- `test_list_search`: testear la búsqueda por nombre, legajo y mail de profesor.
- `test_list_pagination`: testear `limit` y `offset`, y que `limit=0` se rechaza.

## `tests/test_students.py`

**Permisos de alta**
- `test_requires_authentication`: testear que crear alumnos sin login responde 401.
- `test_student_cannot_create_students`: testear que un alumno no puede crear alumnos (403).
- `test_professor_creates_student`: testear que un profesor común puede crear un alumno, que el mail se calcula por legajo y que se envía el mail de bienvenida.

**Alta**
- `test_created_student_can_set_password_and_login`: testear que un alumno recién creado no puede loguearse hasta crear su contraseña, y después sí.
- `test_duplicate_legajo_rejected`: testear que no se puede crear un alumno con un legajo ya existente.
- `test_invalid_student_data`: testear que datos inválidos (año de ingreso fuera de rango) devuelven 422.
- `test_create_student_with_section_year`: testear que el alta con `id_section_year` crea la cursada del alumno en ese curso lectivo.
- `test_create_student_unknown_section_year_rejected`: testear que un curso lectivo inexistente responde 422 con el detalle de la fila y no crea al alumno.
- `test_create_student_unknown_field_rejected`: testear que un campo desconocido en el alta responde 422.
- `test_create_student_under_18_rejected`: testear que un alumno con menos de 18 años no se puede crear (422).
- `test_create_student_exactly_18_allowed`: testear que un alumno que cumple 18 años hoy sí se puede crear.

**Carga masiva**
- `test_bulk_create`: testear que se pueden crear varios alumnos en una sola request.
- `test_bulk_is_all_or_nothing`: testear que si una fila falla no se crea ninguna y el error indica el número de fila.
- `test_bulk_duplicate_inside_request`: testear que un legajo repetido dentro del mismo lote se rechaza.
- `test_bulk_student_under_18_rejected`: testear que si un alumno del lote tiene menos de 18 años se rechaza todo el lote (422).
- `test_bulk_with_section_years`: testear que cada fila puede indicar su curso lectivo y que se crean las cursadas.
- `test_bulk_unknown_section_year_is_all_or_nothing`: testear que un curso lectivo inexistente en una fila rechaza todo el lote (422) con el detalle por fila.

**Modificar un alumno (`PATCH /students/{id}`)**
- `test_patch_requires_authentication`: testear que sin login responde 401.
- `test_student_cannot_patch_students`: testear que un alumno no puede editar alumnos (403).
- `test_professor_edits_student`: testear que un profesor común edita nombre, fecha de nacimiento y año de ingreso, y que lo no enviado no cambia.
- `test_legajo_change_updates_login_mail`: testear que cambiar el legajo cambia el mail de login, conserva la contraseña y el mail viejo deja de servir.
- `test_patch_duplicate_legajo_rejected`: testear que no se puede usar el legajo de otro alumno (409).
- `test_patch_same_legajo_is_ok`: testear que reenviar el propio legajo no da error.
- `test_patch_student_under_18_rejected`: testear que una modificación que deje al alumno con menos de 18 años se rechaza (422).
- `test_student_legajo_may_match_a_professor`: testear que el legajo de un alumno puede coincidir con el de un profesor.
- `test_patch_student_not_found`: testear que un alumno inexistente responde 404.
- `test_patch_student_forbidden_fields`: testear que mail, `is_super_admin` y contraseña no se pueden modificar (422).
- `test_patch_student_empty_body_rejected`: testear que un body vacío se rechaza.
- `test_patch_student_invalid_values_rejected`: testear que se rechaza un año de ingreso fuera de rango y un legajo no positivo.

**Eliminar un alumno (`DELETE /students/{id}`)**
- `test_delete_requires_authentication`: testear que eliminar un alumno sin login responde 401.
- `test_student_cannot_delete_students`: testear que un alumno no puede eliminar alumnos (403).
- `test_regular_professor_cannot_delete_students`: testear que un profesor que no es super admin no puede eliminar alumnos (403).
- `test_super_admin_deletes_student`: testear que un super admin elimina un alumno (204), que desaparece del listado y que ya no puede iniciar sesión.
- `test_delete_frees_legajo`: testear que el legajo queda libre y se puede volver a cargar un alumno con él.
- `test_delete_not_found`: testear que eliminar un alumno inexistente responde 404.
- `test_delete_blocked_by_current_membership`: testear que no se puede eliminar un alumno con alguna membresía `active`, `finished` o `pending_approval` (409), y que el alumno sigue existiendo.
- `test_delete_with_only_past_memberships`: testear que un alumno con solo restos viejos (`abandoned`, `expelled`, `rejected`) se puede eliminar, que esas membresías se borran con él y que los proyectos siguen existiendo.
- `test_delete_removes_sessions_and_otp`: testear que el alumno con una sesión iniciada y un código OTP pendiente se puede eliminar y su refresh token pasa a ser inválido.
- `test_delete_student_with_enrollments`: testear que al eliminar un alumno se borran también sus cursadas.

**Consultar alumnos (`GET /students`)**
- `test_list_requires_authentication`: testear que listar alumnos sin login responde 401.
- `test_student_cannot_list_students`: testear que un alumno no puede listar alumnos (403).
- `test_super_admin_lists_all_students`: testear que un super admin ve todos los alumnos ordenados por apellido, incluso los que no están en ningún grupo (`groups` vacío).
- `test_unassigned_professor_sees_no_students`: testear que un profesor sin cursos lectivos asignados no ve alumnos.
- `test_professor_sees_only_own_section_year`: testear que un profesor común solo ve los alumnos de sus cursos lectivos, con el nombre y número de su grupo.
- `test_groups_list_all_memberships`: testear que un alumno en varias cursadas trae todos sus grupos, con el curso más reciente primero.
- `test_groups_mark_the_leader`: testear que el grupo del alumno indica con `is_leader` si es el jefe del grupo.
- `test_groups_hide_non_current_statuses_by_default`: testear que por defecto solo se listan las membresías `active`/`finished` y que `?status=` permite traer cualquier otro estado.
- `test_groups_ordered_by_status_priority`: testear que dentro de un alumno los grupos se ordenan por estado (los `active` primero) antes que por año.
- `test_list_rejects_unknown_status`: testear que un `status` que no es un estado de membresía válido responde 422.
- `test_scope_filter_respects_membership_status`: testear que al filtrar por curso lectivo solo cuentan las membresías en los estados pedidos.
- `test_list_filters`: testear los filtros `id_section_year`, `year` e `id_section`, solos y combinados.
- `test_list_search`: testear la búsqueda por nombre, apellido, legajo (exacto) y nombre de proyecto (sin distinguir mayúsculas), y que al buscar por proyecto solo cuentan las membresías en los estados pedidos y el alcance.
- `test_professor_cannot_filter_foreign_section_year`: testear que un profesor que filtra un curso lectivo que no dicta recibe 403.
- `test_list_does_not_expose_private_data`: testear que no se expone la fecha de nacimiento ni campos del detalle del proyecto, solo el id, nombre y número del grupo, los datos del curso lectivo, si el alumno es jefe y el estado de la membresía.
- `test_list_pagination`: testear `limit` y `offset`, y que `limit=0` se rechaza.

**Eliminar un usuario (`DELETE /users/{id}`)**
- `test_delete_requires_authentication`: testear que eliminar un usuario sin login responde 401.
- `test_student_cannot_delete_users`: testear que un alumno no puede eliminar usuarios (403).
- `test_regular_professor_cannot_delete_users`: testear que un profesor que no es super admin no puede eliminar usuarios (403).
- `test_super_admin_deletes_student_user`: testear que un super admin elimina a un alumno por esta vía (204) y que ya no puede iniciar sesión.
- `test_delete_student_with_current_membership_rejected`: testear que no se puede eliminar a un alumno con una membresía vigente (409).
- `test_super_admin_deletes_professor_user`: testear que un super admin elimina a un profesor (204) y que ya no puede iniciar sesión.
- `test_delete_professor_with_assignment_rejected`: testear que no se puede eliminar a un profesor asignado a un curso lectivo (409) y que la asignación sigue existiendo.
- `test_delete_super_admin_rejected`: testear que no se puede eliminar a un super admin, ni a uno mismo ni a otro, hasta quitarle el rol (409).
- `test_delete_user_not_found`: testear que un usuario inexistente responde 404.
- `test_delete_frees_mail_and_legajo`: testear que tras eliminar a un profesor se puede volver a crear con el mismo mail y legajo.
- `test_delete_professor_removes_sessions_and_otp`: testear que al eliminar un profesor se cierran sus sesiones (el refresh deja de servir) y se borran sus códigos pendientes.
- `test_delete_student_user_with_enrollments`: testear que eliminar un alumno por `/users/{id}` borra también sus cursadas.

## `tests/test_professors.py`

**Permisos de alta**
- `test_requires_authentication`: testear que crear profesores sin login responde 401.
- `test_student_cannot_create_professors`: testear que un alumno no puede crear profesores (403).
- `test_regular_professor_cannot_create_professors`: testear que un profesor que no es super admin no puede crear profesores (403).
- `test_super_admin_creates_professor`: testear que un super admin puede crear un profesor, que por defecto no es super admin y que se envía el mail de bienvenida.
- `test_created_super_admin_can_create_professors`: testear que un profesor creado como super admin puede a su vez crear profesores.

**Validaciones de alta**
- `test_mail_is_normalized_and_unique`: testear que el mail se guarda en minúsculas y que no se puede repetir (409).
- `test_student_domain_is_reserved`: testear que no se puede registrar un profesor con el dominio de alumnos.
- `test_invalid_mail`: testear que un mail con formato inválido se rechaza.
- `test_professor_legajo_must_be_unique_among_professors`: testear que el legajo de un profesor no puede coincidir con el de otro profesor (409).
- `test_create_professor_under_18_rejected`: testear que un profesor con menos de 18 años no se puede crear (422).
- `test_create_professor_exactly_18_allowed`: testear que un profesor que cumple 18 años hoy sí se puede crear.

**Flujo de cuenta**
- `test_created_professor_sets_password_and_logs_in`: testear que un profesor recién creado crea su contraseña por OTP y luego puede loguearse.

**Modificar un profesor (`PATCH /professors/{id}`)**
- `test_patch_requires_authentication`: testear que sin login responde 401.
- `test_student_cannot_patch_professors`: testear que un alumno no puede editar profesores (403).
- `test_regular_professor_cannot_patch_professors`: testear que un profesor que no es super admin no puede editar profesores (403).
- `test_super_admin_edits_professor`: testear que un super admin edita nombre, legajo y mail, y que el mail se guarda en minúsculas.
- `test_patch_professor_under_18_rejected`: testear que una modificación que deje al profesor con menos de 18 años se rechaza (422).
- `test_mail_change_closes_sessions_and_keeps_password`: testear que cambiar el mail cierra las sesiones del profesor, conserva su contraseña y el mail viejo deja de servir.
- `test_mail_change_notifies_old_and_new_addresses`: testear que al cambiar el mail se envía un aviso a la dirección vieja y a la nueva.
- `test_same_mail_does_not_notify`: testear que reenviar el mismo mail (sin distinguir mayúsculas) no envía ningún aviso.
- `test_patch_duplicate_mail_rejected`: testear que no se puede usar el mail de otro profesor, sin distinguir mayúsculas (409).
- `test_patch_student_domain_is_reserved`: testear que no se puede poner un mail con el dominio de alumnos.
- `test_promote_and_demote_other_professor`: testear que un super admin puede dar y quitar el rol de super admin a otro profesor.
- `test_cannot_remove_own_super_admin`: testear que un super admin no puede quitarse a sí mismo el rol (409).
- `test_super_admin_edits_self`: testear que un super admin puede editar sus propios datos y conserva el rol.
- `test_patch_professor_not_found`: testear que un profesor inexistente responde 404.
- `test_patch_professor_forbidden_fields`: testear que contraseña, id y `email` no se pueden modificar (422).
- `test_patch_professor_empty_body_rejected`: testear que un body vacío se rechaza.

**Eliminar un profesor (`DELETE /professors/{id}`)**
- `test_delete_requires_authentication`: testear que sin login responde 401.
- `test_student_cannot_delete_professors`: testear que un alumno no puede eliminar profesores (403).
- `test_regular_professor_cannot_delete_professors`: testear que un profesor que no es super admin no puede eliminar profesores (403).
- `test_super_admin_deletes_professor`: testear que un super admin elimina a un profesor (204) y deja de existir.
- `test_delete_professor_closes_sessions`: testear que al eliminar un profesor se cierran sus sesiones.
- `test_delete_frees_mail_and_legajo`: testear que tras eliminarlo se puede volver a crear un profesor con el mismo mail y legajo.
- `test_delete_professor_not_found`: testear que un profesor inexistente responde 404.
- `test_cannot_delete_super_admin`: testear que no se puede eliminar a un super admin (409).
- `test_cannot_delete_assigned_professor`: testear que no se puede eliminar a un profesor asignado a un curso lectivo (409).

## `tests/test_sections.py`

**Permisos**
- `test_requires_authentication`: testear que las cinco operaciones sin login responden 401.
- `test_student_cannot_write_sections`: testear que un alumno no puede crear, modificar ni eliminar comisiones (403).
- `test_regular_professor_cannot_write_sections`: testear que un profesor que no es super admin tampoco puede escribir (403).
- `test_any_user_can_read_sections`: testear que un alumno y un profesor común pueden listar y consultar comisiones.

**Crear**
- `test_create_section_normalizes_name`: testear que el nombre se guarda sin espacios sobrantes y en mayúsculas.
- `test_create_duplicate_name_rejected`: testear que no se puede repetir un nombre, sin distinguir mayúsculas (409).
- `test_create_invalid_name_rejected`: testear que se rechaza un nombre vacío, en blanco, de más de 20 caracteres, ausente o con campos desconocidos.

**Consultar**
- `test_list_sections_sorted_by_name`: testear que el listado devuelve todas las comisiones ordenadas por nombre.
- `test_list_search_and_pagination`: testear la búsqueda por nombre, `limit` y `offset`, y que `limit=0` se rechaza.
- `test_get_section`: testear que se puede consultar una comisión por id.
- `test_get_section_not_found`: testear que una comisión inexistente responde 404.

**Modificar**
- `test_rename_section`: testear que se puede renombrar y que el nombre nuevo se normaliza.
- `test_rename_same_name_is_ok`: testear que reenviar el mismo nombre no da error.
- `test_rename_to_existing_name_rejected`: testear que no se puede usar el nombre de otra comisión (409).
- `test_patch_section_not_found`: testear que modificar una comisión inexistente responde 404.
- `test_patch_invalid_rejected`: testear que se rechaza un body vacío, un nombre inválido o campos desconocidos.

**Eliminar**
- `test_delete_section`: testear que se elimina (204) y luego ya no existe ni figura en el listado.
- `test_delete_not_found`: testear que eliminar una comisión inexistente responde 404.
- `test_deleted_name_can_be_reused`: testear que el nombre de una comisión eliminada vuelve a estar disponible.


## `tests/test_section_years.py`

**Permisos**
- `test_requires_authentication`: testear que las cinco operaciones sin login responden 401.
- `test_student_cannot_write_section_years`: testear que un alumno no puede crear, modificar ni eliminar cursos lectivos (403).
- `test_regular_professor_cannot_write_section_years`: testear que un profesor que no es super admin tampoco puede escribir (403).
- `test_any_user_can_read_section_years`: testear que un alumno y un profesor común pueden listar y consultar cursos lectivos.

**Crear**
- `test_create_section_year`: testear que se crea un curso lectivo, que la respuesta incluye el nombre de la comisión y el rango de estudiantes.
- `test_create_duplicate_rejected`: testear que no se puede repetir la combinación año + comisión (409).
- `test_same_section_other_year_and_same_year_other_section_are_ok`: testear que una comisión puede repetirse en otro año y un año en otra comisión.
- `test_create_unknown_section_rejected`: testear que una comisión inexistente responde 404.
- `test_create_invalid_rejected`: testear que se rechaza un año fuera de rango, campos faltantes (incluido el rango de estudiantes), un id no positivo, un rango fuera de 1-100, `max < min` y campos desconocidos.
- `test_create_max_less_than_min_rejected`: testear que crear con `max_students` menor que `min_students` responde 422.

**Consultar**
- `test_list_sorted_by_year_desc_then_section`: testear que el listado ordena por año más reciente y luego por nombre de comisión.
- `test_list_filters_and_pagination`: testear los filtros por año y comisión, `limit` y `offset`, y que `limit=0` se rechaza.
- `test_get_section_year`: testear que se puede consultar un curso lectivo por id.
- `test_get_not_found`: testear que un curso lectivo inexistente responde 404.

**Modificar**
- `test_patch_year`: testear que se puede cambiar el año y la comisión no cambia.
- `test_patch_section`: testear que se puede cambiar la comisión y el año no cambia.
- `test_patch_student_range`: testear que se puede cambiar el rango de estudiantes y que cambiar un solo extremo se valida contra el valor actual del otro.
- `test_patch_year_conflict_with_student_registrations`: testear que cambiar el año de un curso lectivo responde 409 si alguna inscripción quedaría duplicada en ese año.
- `test_patch_year_moves_student_registrations`: testear que al cambiar el año se actualiza la copia de año de las inscripciones/cursadas (el año viejo queda libre y el nuevo ocupa el lugar).
- `test_patch_max_less_than_min_rejected`: testear que dejar `max_students` por debajo de `min_students` responde 422 (enviando ambos o solo uno).
- `test_patch_min_above_max_rejected`: testear que subir `min_students` por encima del `max_students` actual responde 422.
- `test_patch_to_existing_combination_rejected`: testear que no se puede dejar la combinación de otro curso lectivo (409).
- `test_patch_same_values_is_ok`: testear que reenviar los valores actuales no da error.
- `test_patch_not_found`: testear que modificar un curso lectivo inexistente responde 404.
- `test_patch_unknown_section_rejected`: testear que cambiar a una comisión inexistente responde 404.
- `test_patch_invalid_rejected`: testear que se rechaza un body vacío, un año fuera de rango, un id no positivo, un rango de estudiantes fuera de 1-100 y campos desconocidos.

**Configuración**
- `test_allow_project_joins_defaults_to_false`: testear que un curso lectivo nuevo trae `allow_project_joins` en `false`.
- `test_settings_permissions`: testear que sin login responde 401, alumno y profesor no asignado 403, y profesor asignado/super admin 200.
- `test_patch_settings_invalid_body`: testear body vacío, booleano inválido y campos desconocidos (422).
- `test_super_admin_can_set_flag_with_general_patch`: testear que el super admin también puede cambiar `allow_project_joins` con `PATCH /section-years/{id}`.

**Eliminar**
- `test_delete_section_year`: testear que se elimina (204) y luego ya no existe ni figura en el listado.
- `test_delete_not_found`: testear que eliminar un curso lectivo inexistente responde 404.
- `test_cannot_delete_section_in_use`: testear que no se puede eliminar una comisión con cursos lectivos (409) y que sí se puede después de eliminarlos.
- `test_deleted_combination_can_be_reused`: testear que la combinación de un curso lectivo eliminado vuelve a estar disponible.
- `test_delete_with_student_registrations_rejected`: testear que un curso lectivo con inscripciones de alumnos responde 409 y se puede eliminar tras quitarlas.


## `tests/test_student_section_years.py`

Inscripciones y cursadas: qué alumno está inscripto o cursa qué curso lectivo (`POST /student-section-years`, `GET /student-section-years`, `GET /student-section-years/{id}`, `PATCH`, `DELETE`); lectura para profesores y super admin, escritura de la inscripción solo super admin. Las cursadas son de solo lectura por API.

**Permisos**
- `test_requires_authentication`: testear que las cinco operaciones responden 401 sin login.
- `test_student_cannot_read_or_write`: testear que un alumno no puede leer ni escribir (403).
- `test_regular_professor_can_read_but_not_write`: testear que un profesor común puede listar pero no crear (403).

**Crear inscripción**
- `test_create_enrollment`: testear el alta de la inscripción, que nace `registered` y que la respuesta aplana los datos del alumno y del curso lectivo.
- `test_create_duplicate_rejected`: testear que no se puede repetir una inscripción para el mismo alumno y curso lectivo (409).
- `test_create_unknown_references`: testear que un alumno o un curso lectivo inexistente responde 404.
- `test_create_invalid_rejected`: testear ids faltantes, ids no positivos y campos desconocidos (422).
- `test_many_to_many`: testear un alumno con dos inscripciones y un curso lectivo con dos alumnos.
- `test_one_registration_per_year`: testear que un alumno no puede tener dos inscripciones del mismo año (409) aunque sean comisiones distintas, y que otro año sí se permite.
- `test_create_with_state_is_rejected`: testear que el estado no se puede fijar desde el alta (campo desconocido, 422).

**Consultar**
- `test_list_ordering`: testear el orden (año más reciente, comisión y apellido del alumno).
- `test_list_filters`: testear los filtros por alumno, curso lectivo, año y comisión, solos y combinados.
- `test_list_filters_by_state`: testear el filtro por `state` (`registered`, `attending`) y que un estado desconocido responde 422.
- `test_list_pagination`: testear `limit`/`offset`, `total` y que `limit=0` responde 422.
- `test_get_by_id_and_not_found`: testear la consulta por id (un alumno recibe 403) y el 404.
- `test_list_does_not_expose_private_data`: testear que no se expone el mail ni la fecha de nacimiento del alumno.
- `test_registration_and_cursada_coexist`: testear que la inscripción y la cursada conviven como dos filas en la misma comisión.

**Modificar/eliminar la inscripción**
- `test_patch_each_side`: testear que se puede cambiar el alumno y el curso lectivo de una inscripción.
- `test_patch_same_values_is_ok`: testear que reenviar los mismos valores no da error.
- `test_patch_duplicate_pair_rejected`: testear que dejar una inscripción ya existente responde 409.
- `test_patch_to_existing_year_rejected`: testear que mover una inscripción a un alumno que ya tiene otra en ese año responde 409, y que moverla a otro año funciona.
- `test_patch_invalid_and_not_found`: testear body vacío, campos desconocidos (422), referencias inexistentes e inscripción inexistente (404).
- `test_delete_enrollment`: testear que se borra la inscripción (204) y que el alumno y el curso lectivo siguen existiendo.
- `test_delete_not_found`: testear que eliminar una inscripción inexistente responde 404.

**Cursadas administradas**
- `test_managed_cursada_cannot_be_edited_or_deleted`: testear que una cursada no se puede modificar ni borrar por esta vía (409) y sigue existiendo.

## `tests/test_calendars.py`

Calendario del curso lectivo (1 a 1) y sus clases concretas: consulta (`GET /section-years/{id}/calendar`), alta puntual y en lote (`POST .../calendar-classes` y `.../bulk`), modificación y borrado (`PATCH/DELETE /calendar-classes/{id}` y operaciones en lote). Un feriado o suspensión es editar/borrar la clase.

**Permisos**
- `test_requires_authentication`: testear que todos los endpoints responden 401 sin login.
- `test_student_of_other_course_forbidden`: testear que un alumno ajeno al curso lectivo no puede ver ni gestionar el calendario (403).
- `test_enrolled_student_can_read_but_not_write`: testear que un alumno con cursada `attending` puede ver el calendario y una clase, pero no crear (403).
- `test_registration_only_cannot_read`: testear que una inscripción `registered` sola no da acceso al calendario ni a la clase (403).
- `test_finished_cursada_can_read`: testear que una cursada `finished_*` puede ver el calendario y la clase.
- `test_abandoned_cursada_cannot_read`: testear que una cursada `abandoned` sin grupo no puede ver el calendario (403).
- `test_member_of_project_can_read`: testear que un alumno sin cursada pero con un grupo en el curso lectivo puede leer.
- `test_assigned_professor_manages_and_other_cannot`: testear que el profesor asignado gestiona las clases y otro profesor no puede ver ni gestionar (403).
- `test_super_admin_manages_any_course`: testear que el super admin gestiona cualquier curso lectivo.

**Calendario**
- `test_calendar_is_one_per_section_year`: testear que hay un único calendario por curso lectivo y que la respuesta trae calendario, clases y actividades.
- `test_calendar_created_if_missing`: testear que si el curso lectivo viejo no tenía calendario, se crea al consultarlo.
- `test_calendar_range_validation`: testear que se envíen ambos `from`/`to` o ninguno, `from <= to` y rango máximo de 366 días (422).
- `test_calendar_filters_by_range`: testear que el rango filtra las clases devueltas.
- `test_calendar_includes_activities`: testear que el calendario del curso trae sus actividades y que el rango también las filtra.
- `test_calendar_unknown_section_year`: testear que consultar el calendario de un curso lectivo inexistente responde 404.

**Clase puntual**
- `test_create_calendar_class`: testear el alta de una clase con fecha, horario, modalidad y datos opcionales, y que el día de la semana se deriva de la fecha.
- `test_create_validation`: testear fin no posterior al inicio, link inválido, campos faltantes/desconocidos y fecha fuera del año del curso lectivo (422); curso inexistente (404).
- `test_duplicate_and_overlap`: testear que no se repite la misma fecha/hora (409) ni se superponen clases (409), y que tocarse o caer en otro día es válido.
- `test_get_not_found`: testear que una clase inexistente responde 404.
- `test_patch_calendar_class`: testear que se puede mover la fecha, cambiar horario/modalidad/link, limpiar `title`, `location` y `meeting_url` con `null`, y que body vacío, campos desconocidos o fecha fuera del año responden 422.
- `test_patch_overlap_rejected`: testear que mover una clase sobre otra responde 409.
- `test_delete_and_cascade`: testear el borrado (204, deja de existir, 404 al repetir) y que al eliminar el curso lectivo se borra el calendario con sus clases.

**Alta en lote**
- `test_bulk_create`: testear que crea una clase por cada fecha que caiga en los días pedidos (por ejemplo, martes y miércoles de marzo), devueltas ordenadas.
- `test_bulk_conflict_is_all_or_nothing`: testear que si una fecha ya tiene una clase que se superpone responde 409 con el detalle y no crea ninguna.
- `test_bulk_validation`: testear días fuera de 1-7, `from_date > to_date`, fechas fuera del año del curso, ninguna fecha coincidente (422) y días repetidos (se deduplican).

**Modificación en lote**
- `test_bulk_update_by_ids`: testear que modifica las clases elegidas por id.
- `test_bulk_update_by_filter`: testear que modifica solo las clases que cumplen el filtro de días y rango.
- `test_bulk_update_overlap_is_rejected`: testear que si el resultado se superpone con otra clase responde 409 y no modifica nada.
- `test_bulk_update_validation`: testear `ids` y `filter` juntos, sin selector, `changes` vacío, intento de cambiar `date` o ninguna clase coincidente (422).
- `test_bulk_operations_with_foreign_ids`: testear que un `ids` de otro calendario responde 404 al modificar y al borrar, y que la clase ajena sigue existiendo.

**Borrado en lote**
- `test_bulk_delete_by_filter`: testear que se pueden borrar las clases de un día (por ejemplo, un feriado) con un filtro.
- `test_bulk_delete_by_ids`: testear que se pueden borrar clases puntuales por id.
- `test_bulk_delete_validation`: testear sin selector, con ambos selectores o sin coincidencias (422).

## `tests/test_calendar_bulk_load.py`

Carga masiva del calendario (`POST /section-years/{id}/calendar/bulk`): JSON con `classes` y `activities`, append todo o nada y validación previa con `dry_run`.

**Permisos**
- `test_requires_authentication`: testear que cargar sin login responde 401.
- `test_permissions`: testear que alumno y profesor ajeno reciben 403, que el profesor asignado y el super admin cargan, y que un curso inexistente responde 404.

**Carga**
- `test_load_classes_and_activities`: testear la carga de clases y actividades, los conteos de la respuesta y que aparecen en el calendario.
- `test_classes_only_and_activities_only`: testear que se puede enviar solo uno de los arreglos, y que un payload vacío responde 422.
- `test_dry_run_does_not_write`: testear que `dry_run=true` responde 200 con los conteos pero no escribe; confirmar después sí escribe.
- `test_resend_same_load_conflicts`: testear que reenviar la misma carga en append responde 409 y no duplica.
- `test_activities_may_share_hour_with_classes`: testear que una actividad puede compartir fecha/hora con una clase.

**Validaciones**
- `test_dates_and_invalid_data`: testear fechas fuera del año (clase y actividad) con detalle por fila, fin no posterior al inicio, link inválido, campos desconocidos y título de actividad en blanco (422).
- `test_limits`: testear más de 1.000 clases o 200 actividades (422).
- `test_overlaps_within_payload`: testear solapamientos y duplicados exactos dentro del payload (422 con `kind`/`row`) y que no se escribe nada.
- `test_touching_and_same_day_different_times_allowed`: testear clases contiguas y varios horarios no superpuestos el mismo día.
- `test_all_or_nothing_with_invalid_row`: testear que una fila inválida impide crear el resto (clases y actividades).
- `test_conflict_with_existing_is_all_or_nothing`: testear que un choque con una clase existente responde 409 y no crea ni la clase ni la actividad.

## `tests/test_activities.py`

Actividades/entregas del curso lectivo (`GET/POST /section-years/{id}/activities`, `GET/PATCH/DELETE /activities/{id}`): son de todo el curso, con fecha y hora de entrega opcional.

**Permisos**
- `test_requires_authentication`: testear que todos los endpoints responden 401 sin login.
- `test_student_of_other_course_forbidden`: testear que un alumno ajeno al curso no puede ver ni gestionar actividades (403).
- `test_item_permissions`: testear la matriz de permisos por ítem: alumno del curso lee pero no modifica, alumno ajeno no lee, profesor asignado gestiona y profesor ajeno no.
- `test_enrolled_student_can_read_but_not_write`: testear que un alumno con cursada `attending` puede listar y consultar, pero no crear (403).
- `test_registration_only_cannot_read`: testear que una inscripción `registered` sola no da acceso a actividades ni a una actividad (403).
- `test_finished_cursada_can_read`: testear que una cursada `finished_*` puede leer actividades y una actividad.
- `test_abandoned_cursada_cannot_read`: testear que una cursada `abandoned` sin grupo no puede leer actividades (403).
- `test_member_of_project_can_read`: testear que un alumno sin cursada pero con un grupo en el curso lectivo puede leer.
- `test_assigned_professor_manages_and_other_cannot`: testear que el profesor asignado crea, edita y elimina, y que otro profesor no puede ver ni gestionar (403).
- `test_super_admin_manages_any_course`: testear que el super admin gestiona cualquier curso lectivo.

**Crear**
- `test_create_activity`: testear el alta con título, descripción, fecha y hora, y que la respuesta incluye el curso lectivo.
- `test_create_without_optional_fields`: testear que descripción y hora son opcionales.
- `test_create_validation`: testear título vacío o demasiado largo, fecha fuera del año del curso, hora inválida, campos faltantes/desconocidos (422) y curso inexistente (404).
- `test_title_is_trimmed`: testear que el título se recorta.

**Consultar**
- `test_list_ordering_filters_and_pagination`: testear el orden por fecha/hora (sin hora al final), los filtros `from`/`to`, `limit`/`offset`, `total`, los rangos inválidos (422) y el curso lectivo inexistente (404).
- `test_get_not_found`: testear que una actividad inexistente responde 404.

**Modificar**
- `test_patch_activity`: testear cada campo, limpiar descripción y hora con `null`, body vacío, título `null`/en blanco, campos desconocidos, fecha fuera del año (422) y 404.

**Eliminar**
- `test_delete_and_cascade`: testear el borrado (204, 404 al repetir) y que al eliminar el curso lectivo se borran sus actividades.

## `tests/test_me_calendar.py`

Mi calendario (`GET /me/calendar`): clases y actividades de los cursos actuales del usuario, en arreglos separados.

**Permisos**
- `test_requires_authentication`: testear que sin login responde 401.

**Profesores**
- `test_professor_gets_current_year_across_commissions`: testear que con asignaciones en 2025 y 2026 devuelve solo los cursos de 2026 (todas las comisiones) con sus clases y actividades.
- `test_super_admin_with_assignments_gets_calendar`: testear que un super admin que también dicta ve las clases y actividades de sus cursos.

**Alumnos**
- `test_student_gets_current_cursada_year`: testear que con una cursada finalizada en 2025 y una actual en 2026 devuelve solo 2026, con sus clases y actividades.
- `test_student_falls_back_to_current_group`: testear que un alumno sin filas previas que se une a un grupo usa el curso lectivo de ese grupo (la cursada se crea automáticamente).
- `test_registered_student_sees_inscribed_calendar`: testear que un alumno solo inscripto ve por `/me/calendar` el curso, clases y actividades de su inscripción.
- `test_student_prefers_attending_over_registered_for_calendar`: testear que, dentro del mismo año, el calendario corresponde a la cursada `attending` y no a la inscripción `registered`.

**Sin curso actual**
- `test_no_current_section_year`: testear que un profesor sin asignaciones, un alumno sin cursadas ni grupo y un super admin que no dicta reciben los tres arreglos vacíos.

**Reglas**
- `test_range_validation_and_filtering`: testear que el rango es opcional (ambos o ninguno, máximo 366 días) y filtra clases y actividades.
- `test_ordering`: testear que clases y actividades vienen ordenadas por fecha y hora.

## `tests/test_attendance_transcript.py`

Importación de asistencia desde el chat/CSV (`POST /calendar-classes/{id}/attendance/import-transcript` y `.../text`): preview y confirmación, legajo exacto y nombre tolerante.

**Permisos**
- `test_requires_authentication`: testear que ambos endpoints responden 401 sin login.
- `test_permissions`: testear que alumno y profesor ajeno no pueden importar (403), que el profesor asignado sí, que un profesor de otro curso lectivo no, y que una clase inexistente responde 404.

**Preview y confirmación**
- `test_preview_then_confirm`: testear que el preview no escribe, que la confirmación crea con `method: transcript`, que aparece en la lista/historial y que reenviar el archivo es idempotente.
- `test_finished_cursada_is_not_imported`: testear que un alumno con cursada `finished_approved` no se importa y queda como `not_enrolled`.
- `test_existing_attendance_is_not_overwritten`: testear que una asistencia por código no se pisa y se reporta `already_present` con su método original.
- `test_import_does_not_store_the_file`: testear que la importación no guarda el archivo en el almacenamiento.
- `test_report_includes_file_name`: testear que el reporte incluye el nombre del archivo subido.

**Matching del nombre**
- `test_name_tolerance`: testear tildes/espacios, falta del segundo nombre, uso solo del segundo nombre, typo y orden invertido; y que los duplicados se consolidan con `occurrences`.
- `test_name_mismatch_is_not_marked`: testear que solo apellido, solo nombre o el nombre de otro alumno no se marcan y quedan como `name_mismatch`.

**Legajos**
- `test_unknown_and_not_enrolled`: testear alumno no inscripto y legajo de profesor (`not_enrolled`), legajo inexistente o con un dígito de menos (`unknown_legajo`).

**Formatos**
- `test_csv_file_with_header`: testear CSV con encabezado `legajo,apellido,nombre` y filas inválidas.
- `test_csv_text_with_semicolon`: testear CSV pegado con delimitador `;`.
- `test_file_with_bom_and_latin1`: testear UTF-8 con BOM y Latin-1.
- `test_explicit_formats`: testear `format=csv` sobre un `.txt`, `format=text` sobre un `.csv` y CSV pegado con encabezado y dos columnas.
- `test_multiple_attempts_in_one_line`: testear que procesa varias apariciones de legajo-nombre en una misma línea.

**Errores**
- `test_errors`: testear archivo vacío (422), texto sin pares (422), texto con legajo sin nombre (422) y archivo demasiado grande (413).
- `test_empty_text_rejected`: testear que el body de texto vacío responde 422.

## `tests/test_attendance.py`

Asistencia por clase (`/calendar-classes/{id}/attendance`): abrir/rotar/cerrar la toma, check-in del alumno con código, marcado manual del profesor, lista de la clase e historial propio (`GET /me/attendance`).

**Permisos**
- `test_requires_authentication`: testear que abrir, cerrar, check-in, listar, marcar/quitar a mano y el historial responden 401 sin login.
- `test_student_cannot_manage_attendance`: testear que un alumno no puede abrir, cerrar, listar ni marcar a mano (403).
- `test_enrolled_student_cannot_manage_attendance`: testear que un alumno **con cursada** tampoco puede abrir, cerrar, listar ni marcar/quitar a mano (403).
- `test_assigned_professor_manages_and_other_cannot`: testear que el profesor asignado abre, lista, marca y cierra, y que otro profesor no puede (403).
- `test_super_admin_manages_any_course`: testear que el super admin abre, lista, marca y cierra en cualquier curso.
- `test_professor_cannot_check_in`: testear que un profesor no puede marcar su asistencia como alumno (403).

**Abrir y cerrar**
- `test_open_and_close_errors`: testear que abrir/cerrar una clase inexistente responde 404 y cerrar sin toma responde 404.
- `test_rotation_invalidates_previous_code`: testear que reabrir rota el código y que el anterior deja de servir.
- `test_wrong_code_closed_and_expired`: testear código incorrecto (422), toma cerrada (409) y toma vencida (409).
- `test_close_is_idempotent_and_reopen`: testear que cerrar dos veces responde 204, que el check-in queda bloqueado y que reabrir vuelve a habilitarlo.

**Check-in**
- `test_enrolled_student_checks_in`: testear que un alumno con cursada `attending` marca con el código y que aparece en la lista y en su historial.
- `test_registration_only_cannot_check_in`: testear que un alumno solo inscripto (`registered`) no puede marcar con el código (403).
- `test_student_without_cursada_forbidden`: testear que un alumno sin cursada no puede marcar (403).
- `test_check_in_is_idempotent`: testear que repetir el código devuelve la misma marca y no duplica filas.
- `test_code_from_other_class_does_not_work`: testear que el código de otra clase no sirve (422).
- `test_check_in_requires_cursada_in_class_course`: testear que un alumno con cursada en un curso no puede marcar en una clase de otro curso (403).

**Manual y listado**
- `test_manual_mark_and_unmark`: testear el marcado y quitado a mano, la idempotencia y que la lista refleje `present`/`method`.
- `test_manual_foreign_enrollment_rejected`: testear que una cursada de otro curso lectivo responde 422 y una inexistente 404.
- `test_list_includes_all_enrolled_in_order`: testear que la lista incluye a los alumnos con cursada `attending`/`finished_*` (los no marcados en `false`), ordenados por apellido, que excluye inscripciones/abandonadas y que no expone el código.
- `test_list_excludes_registration_and_includes_finished`: testear que una inscripción no aparece en la lista, que una cursada finalizada sí y que trae su `state`.
- `test_manual_mark_registration_rejected`: testear que marcar a mano una inscripción (`registered`) responde 422.
- `test_manual_mark_finished_cursada_rejected`: testear que una cursada `finished_approved` no se puede marcar a mano (422).
- `test_bulk_manual_finished_cursada_rejected`: testear que un lote con una cursada `finished_failed` responde 422 con detalle por fila.
- `test_managed_cursada_cannot_be_deleted`: testear que la cursada no se puede borrar por `/student-section-years` (409) y la asistencia se conserva.
- `test_attendance_errors_for_unknown_class`: testear que listar, marcar o quitar a mano con una clase inexistente responde 404.

**Marcado manual en lote**
- `test_bulk_manual_requires_authentication`: testear que marcar en lote sin login responde 401.
- `test_bulk_manual_permissions`: testear que alumno y profesor ajeno reciben 403, y que el profesor asignado y el super admin pueden.
- `test_bulk_manual_marks_students`: testear que marca varios alumnos como `manual`, respeta el orden y devuelve los conteos y los ítems.
- `test_bulk_manual_is_idempotent`: testear que repetir el lote no duplica y reporta `already_present`.
- `test_bulk_manual_keeps_existing_method`: testear que una asistencia previa por código conserva su método.
- `test_bulk_manual_dedupes`: testear que los IDs repetidos se deduplican y `requested` cuenta únicos.
- `test_bulk_manual_all_or_nothing`: testear que un alumno inexistente o sin cursada responde 422 con detalle por fila y no marca a ninguno.
- `test_bulk_manual_student_from_another_course_rejected`: testear que un alumno cursando otro curso lectivo responde 422.
- `test_bulk_manual_works_with_closed_session`: testear que el lote manual funciona con la toma cerrada.
- `test_bulk_manual_validation`: testear lista vacía, ID no positivo, más de 200 IDs y clase inexistente.

**Historial**
- `test_my_attendance_filters_and_order`: testear que el alumno ve solo lo suyo, con el más reciente primero, filtros de rango y validaciones (422).
- `test_my_attendance_is_student_only`: testear que un profesor recibe 403.
- `test_my_attendance_is_private`: testear que cada alumno ve solo sus propias asistencias y no las de otros.

**Cascadas**
- `test_delete_class_removes_session_and_attendance`: testear que al borrar la clase se van la sesión y las asistencias.
- `test_managed_cursada_cannot_be_deleted`: testear que la cursada no se puede borrar por `/student-section-years` (409) y que la asistencia se conserva.
- `test_delete_student_removes_attendance`: testear que al eliminar al alumno (vía `/users`) se borran sus asistencias.

## `tests/test_professor_section_years.py`

**Permisos**
- `test_requires_authentication`: testear que las cinco operaciones sin login responden 401.
- `test_student_cannot_write`: testear que un alumno no puede asignar, modificar ni quitar profesores (403).
- `test_regular_professor_cannot_write`: testear que un profesor que no es super admin tampoco puede escribir (403).
- `test_any_user_can_read`: testear que un alumno y un profesor común pueden listar y consultar asignaciones.

**Crear**
- `test_create_assignment`: testear que se asigna un profesor a un curso lectivo y la respuesta trae nombre, año y comisión pero ningún dato privado (mail, contraseña).
- `test_create_duplicate_rejected`: testear que no se puede repetir el mismo par profesor + curso lectivo (409).
- `test_many_to_many`: testear que un profesor puede dictar varios cursos lectivos y un curso lectivo puede tener varios profesores.
- `test_create_unknown_references_rejected`: testear que un profesor inexistente, el id de un alumno usado como profesor o un curso lectivo inexistente responden 404.
- `test_create_invalid_rejected`: testear que se rechazan campos faltantes, ids no positivos y campos desconocidos.

**Consultar**
- `test_list_sorted`: testear que el listado ordena por año más reciente, comisión y apellido del profesor.
- `test_list_filters_and_pagination`: testear los filtros por profesor, curso lectivo, año y comisión (también combinados), `limit` y `offset`, y que `limit=0` se rechaza.
- `test_get_assignment`: testear que se puede consultar una asignación por id.
- `test_get_not_found`: testear que una asignación inexistente responde 404.

**Modificar**
- `test_patch_professor`: testear que se puede reasignar a otro profesor y el curso lectivo no cambia.
- `test_patch_section_year`: testear que se puede reasignar a otro curso lectivo y el profesor no cambia.
- `test_patch_to_existing_pair_rejected`: testear que no se puede dejar un par que ya existe (409).
- `test_patch_same_values_is_ok`: testear que reenviar los valores actuales no da error.
- `test_patch_not_found`: testear que modificar una asignación inexistente responde 404.
- `test_patch_unknown_references_rejected`: testear que un profesor inexistente, el id de un alumno o un curso lectivo inexistente responden 404.
- `test_patch_invalid_rejected`: testear que se rechaza un body vacío, ids no positivos y campos desconocidos.

**Eliminar**
- `test_delete_assignment`: testear que se quita la asignación (204) sin borrar al profesor ni al curso lectivo.
- `test_delete_not_found`: testear que eliminar una asignación inexistente responde 404.
- `test_cannot_delete_section_year_in_use`: testear que no se puede eliminar un curso lectivo con profesores asignados (409) y que sí se puede después de quitarlos.
- `test_deleted_assignment_can_be_recreated`: testear que una asignación eliminada puede volver a crearse.

## `tests/test_projects.py`

**Permisos**
- `test_requires_authentication`: testear que las seis operaciones sin login responden 401.
- `test_student_cannot_create_or_delete`: testear que un alumno no puede crear, crear en masa ni eliminar proyectos (403).
- `test_unassigned_professor_cannot_create_or_delete`: testear que un profesor no asignado al curso lectivo no puede crear, crear en masa ni eliminar (403).
- `test_assigned_professor_manages_only_own_section_year`: testear que un profesor asignado puede crear, crear en masa y eliminar solo en su curso lectivo, y no en otros.
- `test_super_admin_manages_any_section_year`: testear que un super admin puede crear y eliminar proyectos en cualquier curso lectivo.

**Crear**
- `test_create_project_defaults`: testear que se crea vacío (nombre, descripción, objetivo y problemática en `null`), público, con el grupo 1 y con el estado inicial `uninsured` (Desasegurado) del ámbito `project`.
- `test_create_assigns_first_free_group_number`: testear que sin `group_number` toma el primer hueco libre (no el mayor + 1), también después de números explícitos, y que sin huecos continúa después del mayor.
- `test_create_duplicate_group_number_rejected`: testear que no se repite el número de grupo dentro del curso lectivo (409).
- `test_same_group_number_in_other_section_year_is_ok`: testear que el mismo número puede existir en otro curso lectivo.
- `test_create_unknown_section_year`: testear que un curso lectivo inexistente responde 404.
- `test_create_invalid_rejected`: testear que se rechazan campos faltantes, ids o números no positivos y campos no permitidos (privacidad, nombre).

**Crear en masa**
- `test_bulk_create`: testear que se crean grupos consecutivos, todos con el estado inicial, y que una segunda tanda continúa la numeración.
- `test_bulk_reuses_freed_group_number`: testear que tras eliminar un grupo intermedio la masiva reutiliza ese hueco.
- `test_bulk_uses_first_free_numbers`: testear que la masiva usa los primeros números libres aunque haya huecos (por ejemplo, con 1, 2, 3 y 6 crea 4, 5 y 7).
- `test_bulk_unknown_section_year`: testear que un curso lectivo inexistente responde 404.
- `test_bulk_invalid_rejected`: testear que se rechaza una cantidad fuera de 1-50, campos faltantes y campos desconocidos.

**Consultar**
- `test_list_sorted_and_filtered`: testear el orden (año, comisión, grupo), los filtros por curso lectivo, año, comisión y privacidad (efectiva: un `uninsured` cuenta como `public`).
- `test_list_search_by_name`: testear la búsqueda por nombre de proyecto (parcial y sin distinguir mayúsculas), sin coincidencias, combinada con año, que un proyecto sin nombre no matchea y que `q` vacío responde 422.
- `test_list_pagination`: testear `limit` y `offset`, y que `limit=0` se rechaza.
- `test_get_not_found`: testear que un proyecto inexistente responde 404.

**Visibilidad según privacidad**
- `test_uninsured_project_is_public_regardless_of_privacy`: testear que un proyecto `uninsured` con privacidad `private` se ve como público (`privacy` efectiva `public`, detalle completo) para cualquiera.
- `test_public_project_detail_visible_to_everyone`: testear que un alumno cualquiera y un profesor ajeno ven el detalle de un proyecto público.
- `test_protected_project_basic_visible_to_outsiders`: testear que en un proyecto protegido un alumno no miembro y un profesor ajeno ven solo la información básica (`restricted` en `true` y el detalle en `null`), tanto en el listado como al consultarlo.
- `test_protected_project_detail_visible_to_privileged`: testear que un miembro, un profesor del curso lectivo y un super admin ven el detalle completo de un proyecto protegido.
- `test_private_project_hidden_from_outsiders`: testear que en un proyecto privado un alumno no miembro y un profesor ajeno no lo ven en el listado y reciben 403 al consultarlo.
- `test_private_project_detail_visible_to_members_and_staff`: testear que un miembro, un profesor del curso lectivo y un super admin ven el detalle de un proyecto privado, y que otro alumno no lo ve ni en el listado ni en el detalle.
- `test_pending_member_has_no_privileges`: testear que un alumno con membresía `pending_approval` no cuenta como privilegiado y solo ve la información básica de un proyecto protegido.
- `test_abandoned_member_loses_privileges_on_private_project`: testear que un alumno con membresía `abandoned` no ve un proyecto privado (ni en el listado ni al consultarlo).
- `test_finished_member_keeps_privileges`: testear que un alumno con membresía `finished` sigue viendo el detalle de un proyecto privado.
- `test_assigned_professor_sees_all_projects_of_own_section_year`: testear que un profesor asignado a un curso lectivo ve el detalle completo de todos sus proyectos (públicos, protegidos y privados) filtrando por ese curso lectivo.

**Modificar**
- `test_patch_requires_privilege`: testear que un alumno no miembro y un profesor no asignado no pueden modificar un proyecto (403).
- `test_pending_member_cannot_patch`: testear que un alumno con membresía `pending_approval` no puede modificar el proyecto (403).
- `test_member_can_patch_private_project`: testear que un miembro `active` modifica los atributos de un proyecto privado (200).
- `test_finished_member_can_patch`: testear que un miembro con membresía `finished` puede modificar el proyecto.
- `test_assigned_professor_can_patch`: testear que un profesor del curso lectivo puede modificar el proyecto.
- `test_super_admin_can_patch`: testear que un super admin puede modificar cualquier proyecto.
- `test_patch_each_field`: testear que se editan `name`, `description`, `objective`, `problem` y `privacy`, y que el estado no cambia.
- `test_patch_only_changes_sent_fields`: testear que lo no enviado no cambia.
- `test_patch_same_values_is_ok`: testear que reenviar los mismos valores no da error.
- `test_patch_can_clear_optional_fields`: testear que enviar `null` en un campo de texto lo limpia.
- `test_patch_privacy_null_rejected`: testear que `privacy` con `null` responde 422.
- `test_patch_empty_body_rejected`: testear que un body vacío responde 422.
- `test_patch_invalid_rejected`: testear que un `name` en blanco, una `privacy` inválida o un campo no permitido (`group_number`) responden 422.
- `test_patch_not_found`: testear que un proyecto inexistente responde 404.
- `test_cannot_patch_final_project`: testear que un proyecto en estado final (`approved`/`cancelled`) no se puede modificar (409).

**Eliminar**
- `test_delete_empty_project`: testear que se elimina un proyecto vacío (204) y deja de figurar.
- `test_delete_not_found`: testear que eliminar un proyecto inexistente responde 404.
- `test_cannot_delete_project_with_students`: testear que no se puede eliminar un proyecto con alumnos (409).
- `test_cannot_delete_insured_project`: testear que no se puede eliminar un proyecto asegurado (por ejemplo `in_idea`) aunque esté vacío (409).
- `test_cannot_delete_final_project`: testear que no se puede eliminar un proyecto en estado final (por ejemplo `approved`) aunque esté vacío (409).
- `test_deleted_group_number_can_be_reused`: testear que un número de grupo eliminado se puede volver a crear enviándolo y que el alta automática también lo reutiliza.
- `test_cannot_delete_section_year_with_projects`: testear que no se puede eliminar un curso lectivo con proyectos (409) y que sí se puede después de eliminarlos.

## `tests/test_project_statuses.py`

Historial de estados de un proyecto (`GET /projects/{id}/status-history`).

**Permisos**
- `test_requires_authentication`: testear que consultar el historial sin login responde 401.
- `test_private_project_history_hidden_from_outsiders`: testear que un alumno no privilegiado recibe 403 al pedir el historial de un proyecto privado.
- `test_history_visible_for_public_project`: testear que un alumno cualquiera puede ver el historial de un proyecto público.

**Consultar**
- `test_history_has_initial_record_after_create`: testear que al crear un proyecto queda un registro inicial con `status_from` en `null` y `status_to` en `uninsured`.
- `test_history_returns_public_fields`: testear que cada registro expone `id_project_status`, `id_project`, `status_from`, `status_to` y `changed_at`, y que no se filtra nada.
- `test_history_order_is_chronological`: testear que los registros vienen en orden cronológico (el más viejo primero).
- `test_history_pagination`: testear `limit` y `offset`, y que `limit=0` se rechaza (422).
- `test_history_not_found`: testear que un proyecto inexistente responde 404.

## `tests/test_project_overview.py`

Proyecto con sus integrantes, sus responsables (los profesores asignados a su curso lectivo, sin mail) y su jefe (`GET /projects/{id}/overview`).

**Permisos**
- `test_requires_authentication`: testear que consultar el overview sin login responde 401.
- `test_unknown_project`: testear que un proyecto inexistente responde 404.
- `test_private_overview_hidden_from_outsiders`: testear que un alumno no miembro y un profesor no asignado reciben 403 en un proyecto privado.
- `test_non_privileged_cannot_filter_status`: testear que un usuario no privilegiado que envía `status` recibe 403.

**Visibilidad**
- `test_uninsured_overview_shows_detail_and_members`: testear que un proyecto `uninsured` se ve completo (aunque su privacidad almacenada sea `private`, la efectiva es `public`) con sus integrantes, su jefe y `responsible` vacío si el curso no tiene profesores asignados.
- `test_public_overview_full_detail_and_members`: testear que en un proyecto público cualquiera ve el detalle completo, los integrantes y el jefe.
- `test_protected_overview_basic_for_outsiders`: testear que en un proyecto protegido el no privilegiado ve `restricted` en `true` y el detalle en `null`, pero recibe igual los integrantes y el jefe.
- `test_protected_overview_full_for_privileged`: testear que un miembro, el profesor del curso lectivo y el super admin ven el detalle completo de un proyecto protegido.
- `test_private_overview_full_for_privileged`: testear que un miembro, el profesor del curso lectivo y el super admin ven el detalle de un proyecto privado, con los responsables (profesores del curso) y el jefe.
- `test_overview_without_leader`: testear que un proyecto sin integrantes devuelve `members` vacío, `leader` en `null` y `responsible` vacío.

**Filtro de estados**
- `test_overview_default_members_are_active_and_finished`: testear que por defecto se listan los estados `active` y `finished` (categoría `member`), sin los `pending_approval`.
- `test_overview_privileged_can_filter_status`: testear que un privilegiado puede pedir repetidamente `status` (una combinación) y que el jefe se resuelve aparte del filtro.
- `test_overview_invalid_status`: testear que un `status` fuera de los permitidos responde 422.

**Datos del integrante**
- `test_overview_member_fields_and_order`: testear que cada integrante expone los datos públicos del alumno, `is_leader`, `enrolled_at` (datetime ISO) y `status` (sin el mail), que el jefe va primero y que `leader` coincide con el integrante marcado como jefe.

**Responsables (profesores del curso lectivo)**
- `test_overview_responsible_are_section_year_professors`: testear que `responsible` lista los profesores asignados al curso lectivo (orden, campos `id_professor`/`first_name`/`last_name`/`legajo` y sin mail ni `is_super_admin`).
- `test_overview_responsible_visible_to_outsider_in_protected`: testear que en un proyecto protegido el no privilegiado igual recibe los responsables.
- `test_overview_responsible_empty_after_assignment_removed`: testear que al quitar una asignación el overview refleja los responsables al momento (lista vacía).

## `tests/test_project_insure.py`

Aseguramiento de un proyecto (`POST /projects/{id}/insure`).

**Permisos**
- `test_requires_authentication`: testear que asegurar sin login responde 401.
- `test_leader_can_insure`: testear que el jefe del grupo (`active`) asegura el proyecto (200, queda `in_idea`).
- `test_assigned_professor_can_insure`: testear que un profesor del curso lectivo puede asegurar.
- `test_super_admin_can_insure`: testear que un super admin puede asegurar.
- `test_non_member_student_cannot_insure`: testear que un alumno que no es del grupo recibe 403.
- `test_non_leader_active_member_cannot_insure`: testear que un integrante `active` que no es jefe recibe 403.
- `test_unassigned_professor_cannot_insure`: testear que un profesor no asignado al curso lectivo recibe 403.
- `test_pending_member_cannot_insure`: testear que un integrante `pending_approval` (no privilegiado) recibe 403.

**Reglas**
- `test_insure_moves_to_in_idea_by_default`: testear que sin memoria el proyecto queda `in_idea`, un estado asegurado.
- `test_cannot_insure_already_insured`: testear que asegurar un proyecto ya asegurado responde 409.
- `test_cannot_insure_final_project`: testear que asegurar un proyecto final (`approved`/`cancelled`) responde 409.
- `test_insure_unknown_project`: testear que un proyecto inexistente responde 404.
- `test_insure_requires_min_students`: testear que con menos de `min_students` integrantes `active` responde 409.
- `test_insure_with_exactly_min_students`: testear que con exactamente `min_students` integrantes `active` se puede asegurar.
- `test_insure_rejects_more_than_max_students`: testear que con más de `max_students` integrantes `active` responde 409.

**Efectos**
- `test_insure_records_history`: testear que el aseguramiento agrega la transición `uninsured → in_idea` al historial.
- `test_cannot_join_after_insure`: testear que después de asegurar ya no se puede unir un integrante nuevo (409).
- `test_insure_rejects_pending_requests`: testear que al asegurar las solicitudes `pending_approval` pasan a `rejected` y el jefe sigue `active`.
- `test_insure_makes_private_privacy_apply`: testear que un proyecto guardado `private` deja de verse como público al asegurarse (antes 200 para un tercero, después 403).

**Memoria del subestado**
- `test_insure_defaults_to_in_idea_without_memory`: testear que sin subestado recordado el proyecto vuelve a `in_idea`.
- `test_insure_returns_to_remembered_status`: testear que con el subestado recordado (`in_progress`) el proyecto vuelve a él y el historial lo refleja.

## `tests/test_project_transitions.py`

Transiciones de estado del proyecto (`POST /projects/{id}/uninsure`, `/start`, `/submit`, `/approve`, `/reject`, `/retry`, `/cancel`). Todas son por un profesor del curso lectivo o un super admin.

**Permisos**
- `test_requires_authentication`: testear que cualquier transición sin login responde 401.
- `test_student_cannot_change_status`: testear que un alumno recibe 403 en todas las transiciones.
- `test_group_leader_cannot_change_status`: testear que el jefe del grupo (alumno) recibe 403.
- `test_unassigned_professor_cannot_change_status`: testear que un profesor no asignado al curso lectivo recibe 403.
- `test_assigned_professor_can_change_status`: testear que un profesor del curso lectivo puede cambiar el estado.
- `test_super_admin_can_change_status`: testear que un super admin puede cambiar el estado.
- `test_unknown_project`: testear que un proyecto inexistente responde 404 en todas las transiciones.

**Transiciones válidas**
- `test_uninsure_from_each_insured_status`: testear que `uninsure` funciona desde `in_idea`, `in_progress`, `pending_approval` y `rejected`, y que el proyecto vuelve a tratarse como público.
- `test_uninsure_writes_memory`: testear que `uninsure` guarda el subestado saliente en `id_status_insured`.
- `test_uninsure_then_insure_returns_to_same_substate`: testear que tras `uninsure` el `insure` retoma el subestado recordado.
- `test_start_moves_idea_to_progress`: testear que `start` pasa de `in_idea` a `in_progress`.
- `test_submit_moves_progress_to_pending`: testear que `submit` pasa de `in_progress` a `pending_approval`.
- `test_approve_moves_pending_to_approved`: testear que `approve` pasa de `pending_approval` a `approved`.
- `test_reject_moves_pending_to_rejected`: testear que `reject` pasa de `pending_approval` a `rejected`.
- `test_retry_moves_rejected_to_progress`: testear que `retry` pasa de `rejected` a `in_progress`.
- `test_cancel_from_uninsured`: testear que un proyecto `uninsured` se puede cancelar.
- `test_cancel_from_each_insured_status`: testear que `cancel` funciona desde cada estado asegurado.

**Transiciones no permitidas**
- `test_cannot_uninsure_from_uninsured`: testear que `uninsure` desde `uninsured` responde 409.
- `test_transition_not_allowed`: testear que una transición fuera de la máquina de estados responde 409.
- `test_cannot_cancel_final_project`: testear que cancelar un proyecto final (`approved`) responde 409.
- `test_cannot_change_status_of_final_project`: testear que ningún endpoint cambia el estado de un proyecto final (`cancelled`) (409).

**Efectos en las membresías e historial**
- `test_cancel_abandons_active_members`: testear que `cancel` pasa las membresías `active` a `abandoned`.
- `test_cancel_rejects_pending_requests`: testear que `cancel` pasa las membresías `pending_approval` a `rejected`.
- `test_approve_finishes_active_members`: testear que `approve` pasa las membresías `active` a `finished`.
- `test_approve_finishes_cursada`: testear que al aprobar el proyecto su cursada `attending` pasa a `finished_approved`.
- `test_cancel_marks_cursada_finished_failed`: testear que al cancelar el proyecto su cursada `attending` pasa a `finished_failed`.
- `test_history_records_each_transition`: testear que cada transición se registra en el historial en orden.
- `test_full_rejection_cycle`: testear que el ciclo `insure → start → submit → reject → retry → submit` funciona.

## `tests/test_student_projects.py`

Integrantes del proyecto: unirse a un grupo (`POST /projects/{id}/members`), aceptar/rechazar solicitudes (`PATCH /projects/{id}/members/{id_student_project}`), abandonar (`POST .../abandon`), expulsar (`POST .../expel`), delegar la jefatura (`POST .../leader`) y listar integrantes (`GET /projects/{id}/members`).

**Permisos**
- `test_requires_authentication`: testear que unirse, listar, aceptar/rechazar, abandonar, expulsar y delegar sin login responden 401.
- `test_professor_cannot_join`: testear que un profesor o super admin no puede unirse a un grupo (403; solo alumnos).
- `test_professor_cannot_abandon`: testear que un profesor recibe 403 al querer abandonar (solo alumnos).
- `test_non_leader_cannot_decide`: testear que un alumno que no es el jefe, un profesor y el super admin reciben 403 al aceptar o rechazar.

**Unirse**
- `test_first_member_becomes_leader_and_active`: testear que el primer integrante de un grupo vacío entra como jefe y `active`.
- `test_second_member_is_pending_and_not_leader`: testear que, si ya hay jefe, el siguiente queda `pending_approval` y no es jefe.
- `test_cannot_join_insured_project`: testear que no se puede pedir entrar a un proyecto que no está `uninsured` (409).
- `test_join_unknown_project`: testear que un proyecto inexistente responde 404.
- `test_cannot_request_twice`: testear que no se puede volver a pedir entrar si ya se es miembro o si hay una solicitud pendiente (409).
- `test_rejected_can_request_again`: testear que una solicitud `rejected` se puede volver a enviar (200) y queda `pending_approval`.
- `test_cannot_join_empty_group_when_member_elsewhere`: testear que un alumno que ya es `member` de otro grupo no puede unirse a uno vacío (sería jefe/`active`): 409.
- `test_member_elsewhere_cannot_request_join`: testear que un alumno `member` (`active`/`finished`) de otro grupo no puede solicitar entrar a otro (409), aunque tenga jefe; debe abandonar primero.
- `test_member_elsewhere_cannot_resend_rejected_request`: testear que si el alumno ya es `member` de otro grupo, no puede reenviar una solicitud `rejected` (409).
- `test_student_with_only_pending_elsewhere_can_still_request`: testear que un alumno con solo solicitudes `pending_approval` en otros grupos sí puede pedir a otro, y al convertirse en `member` sus otras `pending_approval` pasan a `rejected`.
- `test_becoming_member_rejects_other_pending`: testear que al pasar a `member`, las otras solicitudes `pending_approval` del alumno pasan a `rejected`.

**Aceptar / rechazar**
- `test_leader_accepts_request`: testear que el jefe acepta una solicitud y el alumno queda `active` (sin ser jefe).
- `test_leader_rejects_request`: testear que el jefe rechaza una solicitud y el alumno queda `rejected`.
- `test_decide_invalid_transition`: testear que una transición no permitida (por ejemplo `active → active` o `active → rejected`) responde 409.
- `test_accept_when_student_already_member`: testear que aceptar a un alumno que ya es `member` de otro grupo responde 409.
- `test_decide_membership_not_found`: testear que una membresía inexistente o de otro proyecto responde 404.
- `test_decide_invalid_body`: testear que un `status` faltante, distinto de `active`/`rejected` o un campo desconocido responden 422.

**Abandonar**
- `test_member_can_abandon`: testear que un integrante `active` abandona su grupo (204) y su membresía queda `abandoned` y sin jefatura.
- `test_cannot_abandon_someone_else`: testear que un alumno no puede abandonar la membresía de otro (403).
- `test_cannot_abandon_pending`: testear que una membresía `pending_approval` no se puede abandonar (409).
- `test_cannot_abandon_insured_project`: testear que no se puede abandonar si el proyecto no está `uninsured` (409).
- `test_abandon_unknown_membership`: testear que una membresía inexistente responde 404.
- `test_leader_abandon_promotes_oldest_active`: testear que al abandonar el jefe, la jefatura pasa al integrante `active` más antiguo (`enrolled_at`).
- `test_leader_abandon_without_successor_leaves_no_leader`: testear que si el jefe abandona y no queda ningún `active`, el grupo queda sin jefe.

**Expulsar**
- `test_professor_can_expel`: testear que el profesor del curso lectivo expulsa a un integrante `active` (204) y queda `expelled`.
- `test_super_admin_can_expel`: testear que el super admin puede expulsar.
- `test_unassigned_professor_cannot_expel`: testear que un profesor no asignado al curso lectivo recibe 403.
- `test_leader_cannot_expel`: testear que el jefe (alumno) no puede expulsar (403).
- `test_cannot_expel_pending`: testear que una membresía `pending_approval` no se puede expulsar (409).
- `test_cannot_expel_in_insured_project`: testear que no se puede expulsar si el proyecto no está `uninsured` (409).
- `test_expel_unknown_membership`: testear que una membresía inexistente responde 404.
- `test_expel_leader_promotes_oldest_active`: testear que al expulsar al jefe, la jefatura pasa al integrante `active` más antiguo.

**Añadir integrante**
- `test_add_requires_authentication`: testear que sin login responde 401.
- `test_student_cannot_add_member`: testear que un alumno no puede añadir integrantes (403).
- `test_unassigned_professor_cannot_add_member`: testear que un profesor no asignado al curso lectivo recibe 403.
- `test_professor_can_add_member`: testear que un profesor asignado añade un alumno como `active` y, si el grupo estaba vacío, como jefe (201).
- `test_super_admin_can_add_member`: testear que el super admin puede añadir un alumno (`active`, no jefe si ya había jefe) (201).
- `test_add_unknown_student`: testear que un alumno inexistente responde 404.
- `test_add_unknown_project`: testear que un proyecto inexistente responde 404.
- `test_cannot_add_in_insured_project`: testear que no se puede añadir si el proyecto no está `uninsured` (409).
- `test_cannot_add_already_member`: testear que un alumno que ya pertenece al proyecto en otro estado responde 409.
- `test_cannot_add_member_of_another_project`: testear que un alumno que ya es `member` de otro proyecto responde 409.
- `test_add_reactivates_rejected_membership`: testear que una solicitud `rejected` previa se reactiva como `active` (200).
- `test_add_rejects_other_pending_requests`: testear que al añadir se rechazan las otras solicitudes `pending_approval` del alumno.

**Delegar jefatura**
- `test_leader_can_transfer_leadership`: testear que el jefe delega la jefatura en otro integrante `active` (200) y deja de ser jefe.
- `test_cannot_transfer_to_pending`: testear que no se puede delegar a un integrante `pending_approval` (409).
- `test_cannot_transfer_to_self`: testear que el jefe no puede delegarse la jefatura a sí mismo (409).
- `test_non_leader_cannot_transfer`: testear que un integrante `active` que no es jefe recibe 403.
- `test_transfer_allowed_in_insured_project`: testear que la delegación se permite en un proyecto asegurado (no final).
- `test_cannot_transfer_in_final_project`: testear que no se puede delegar en un proyecto final (`approved`/`cancelled`): 409.
- `test_transfer_unknown_membership`: testear que una membresía inexistente responde 404.

**Consultar**
- `test_outsider_cannot_list`: testear que un alumno sin privilegios sobre el proyecto no puede listar integrantes (403).
- `test_member_can_list_and_leader_is_first`: testear que un miembro lista integrantes, el jefe va primero, no se expone el mail y se incluye `enrolled_at` como datetime ISO.
- `test_staff_can_list`: testear que el profesor del curso lectivo y el super admin pueden listar integrantes.
- `test_list_unknown_project`: testear que un proyecto inexistente responde 404.
- `test_list_filter_and_pagination`: testear el filtro por `status`, `limit`/`offset` y que un `status` inválido o `limit=0` responden 422.


**Cursadas automáticas**
- `test_join_creates_attending`: testear que unirse como `active` crea la cursada `attending` del curso lectivo.
- `test_join_rejects_project_of_another_year`: testear que el proyecto debe ser del año actual del alumno (409).
- `test_pending_request_does_not_create_cursada`: testear que una solicitud `pending_approval` no crea cursada.
- `test_accepting_request_creates_attending`: testear que al aceptar la solicitud se crea la cursada `attending`.
- `test_add_member_creates_attending`: testear que añadir a un alumno como `active` crea su cursada `attending`.
- `test_abandon_and_rejoin_reactivates_cursada`: testear que abandonar deja la cursada `abandoned` y reincorporarse a la misma comisión reactiva la misma fila.
- `test_changing_section_year_abandons_previous_cursada`: testear que al pasar a otra comisión del mismo año la cursada anterior queda `abandoned` y se crea la nueva `attending`.
- `test_expel_abandons_cursada`: testear que expulsar a un integrante deja su cursada `abandoned`.
- `test_join_uses_attending_year_over_newer_registration`: testear que el año del proyecto se valida contra la cursada `attending` y no contra una inscripción más nueva.
- `test_join_ignores_newer_abandoned_cursada`: testear que una cursada abandonada de un año más nuevo no bloquea unirse al año actual.
- `test_finished_failed_rejoin_blocked_by_default`: testear que un proyecto cancelado bloquea volver a la misma comisión si `allow_project_joins=false` (409).
- `test_finished_failed_rejoin_allowed_with_flag`: testear que con `allow_project_joins=true` se reactiva la cursada `attending`.
- `test_finished_approved_rejoin_blocked_even_with_flag`: testear que `finished_approved` no se puede reintentar aunque el flag esté activo (409).

## `tests/test_me_project.py`

Mi proyecto (`GET /me/project`): el equipo donde el alumno es miembro y sus solicitudes de ingreso.

**Permisos**
- `test_requires_authentication`: testear que consultar sin login responde 401.
- `test_professor_and_super_admin_forbidden`: testear que un profesor (común o super admin) recibe 403 (solo alumnos).

**Consultar**
- `test_no_team_and_no_requests`: testear que un alumno sin equipo y sin solicitudes recibe `{"project": null, "requests": []}`.
- `test_team_with_leader_responsible_and_overview_fields`: testear que el proyecto propio viene con el overview completo (estado, privacidad efectiva, integrantes, `leader`, responsables del curso lectivo) y sin `restricted`.
- `test_member_data_has_no_private_fields`: testear que los integrantes exponen solo datos públicos (sin mail ni fecha de nacimiento).
- `test_finished_membership_is_still_the_team`: testear que una membresía `finished` sigue siendo el equipo (proyecto finalizado) y que conserva la jefatura en `leader`.
- `test_private_team_seen_in_full_by_its_member`: testear que en un proyecto `private` el miembro ve todo el detalle (`restricted` en `false`).
- `test_pending_request_with_no_team`: testear que una solicitud `pending_approval` aparece en `requests` con el resumen del grupo y `project` en `null`.
- `test_rejected_request_while_member_of_another_project`: testear que una solicitud `rejected` se ve aunque el alumno ya tenga equipo.
- `test_requests_ordered_pending_first_then_by_newest`: testear que `requests` ordena pendientes primero y, entre rechazadas, de la más nueva a la más vieja.
- `test_abandoned_and_expelled_are_not_requests`: testear que `abandoned` y `expelled` no cuentan como equipo ni como solicitudes.

## `tests/test_me_section_year.py`

Mi curso lectivo actual (`GET /me/section-year`) y sus proyectos (`GET /me/section-year/projects`): el año actual del profesor (por asignaciones) o del alumno (`attending`, luego la última `finished_*`, luego la última `registered`, con fallback a su grupo), con la privacidad de siempre.

**Permisos**
- `test_requires_authentication`: testear que ambos endpoints responden 401 sin login.

**Profesores**
- `test_professor_gets_latest_section_year`: testear que con cursos 2025 y 2026 devuelve solo el de 2026 y que los proyectos son solo de ese curso.
- `test_professor_with_two_commissions_in_latest_year`: testear que si dicta dos comisiones del mismo año devuelve ambas y los proyectos de las dos.
- `test_super_admin_with_assignments_gets_courses`: testear que un super admin que también dicta ve sus cursos y proyectos.

**Alumnos**
- `test_student_gets_latest_enrolled_year`: testear que con una cursada finalizada en 2025 y una cursada actual en 2026 devuelve solo 2026 y sus proyectos.
- `test_student_prefers_attending_over_registered`: testear que dentro del mismo año prevalece la cursada `attending` sobre la inscripción `registered`.
- `test_student_attending_wins_over_newer_registration`: testear que una cursada `attending` de un año anterior prevalece sobre una inscripción de un año más nuevo.
- `test_student_finished_wins_over_newer_registration`: testear que una cursada `finished_*` prevalece sobre una inscripción de un año más nuevo.
- `test_student_uses_registration_when_no_cursada`: testear que, sin cursadas, se usa la última inscripción `registered`.
- `test_student_uses_finished_when_no_newer`: testear que una cursada `finished_approved` se devuelve si no hay una más nueva.
- `test_student_ignores_abandoned_cursada`: testear que una cursada `abandoned` no se considera curso actual.
- `test_student_ignores_newer_abandoned_year`: testear que una cursada abandonada de un año más nuevo no tapa la cursada de un año anterior.
- `test_student_falls_back_to_current_group`: testear que un alumno sin filas previas que se une a un grupo usa el curso lectivo de ese grupo (la cursada se crea automáticamente).

**Sin curso actual**
- `test_no_current_section_year`: testear que un profesor sin asignaciones, un alumno sin cursadas ni grupo y un super admin que no dicta reciben `section_years` vacío y proyectos vacíos (200).

**Reglas**
- `test_projects_follow_privacy`: testear que en los proyectos del curso actual el privado ajeno no aparece, el protegido viene `restricted` con el detalle en `null`, el público completo, y que el profesor de ese curso lectivo ve todo.
- `test_ordering_and_pagination`: testear el orden por número de grupo, `limit`/`offset`, `total` y que `limit=0` responde 422.

## `tests/test_images.py`

Imágenes del sistema (`POST /images`, `GET /images/{id}`, `DELETE /images/{id}`): subida multipart para profesores y super admin, consulta para cualquier usuario logueado, conversión a WebP, límites de tamaño y borrado del archivo en disco.

**Permisos**
- `test_requires_authentication`: testear que subir, consultar y eliminar responden 401 sin login.
- `test_student_cannot_write`: testear que un alumno no puede subir ni eliminar imágenes (403).
- `test_professor_can_upload`: testear que un profesor común puede subir imágenes.

**Subir**
- `test_upload_converts_to_webp_and_saves_file`: testear que jpeg, png y webp se aceptan, que la respuesta informa `content_type` `image/webp` con la `url` de `/media` y que el archivo guardado en disco es WebP.
- `test_upload_metadata_and_get`: testear que la consulta por id devuelve los mismos datos (cualquier usuario logueado) y que un id inexistente responde 404.
- `test_upload_rejects_invalid_content`: testear que un gif, un archivo que no es imagen y un archivo vacío responden 422.
- `test_upload_rejects_too_large`: testear que un archivo mayor a 5 MB responde 413.
- `test_upload_original_name_is_sane`: testear que el nombre original se sanea (sin rutas ni `../`, espacios colapsados).

**Eliminar**
- `test_delete_image`: testear que elimina la fila y el archivo, y que un id inexistente responde 404.
- `test_media_file_is_served_publicly`: testear que el archivo se sirve sin login desde `/media/...`.

## `tests/test_technologies.py`

Tecnologías: alta, edición, consulta y baja del catálogo (`POST /technologies`, `GET /technologies`, `GET /technologies/{id}`, `PATCH /technologies/{id}`, `DELETE /technologies/{id}`) y su imagen (`PUT /technologies/{id}/image`, `DELETE /technologies/{id}/image`, `id_image` en JSON y `file` en multipart); escritura para profesores y super admin, lectura para cualquier usuario logueado.

**Permisos**
- `test_requires_authentication`: testear que todos los endpoints responden 401 sin login.
- `test_student_cannot_write`: testear que un alumno no puede crear, editar ni eliminar tecnologías (403).
- `test_regular_professor_can_write`: testear que un profesor común puede crear, editar y eliminar tecnologías.
- `test_any_user_can_read`: testear que un alumno logueado puede listar y consultar una tecnología con sus datos completos.

**Crear**
- `test_create_technology`: testear el alta con normalización del nombre (recorta espacios y conserva el casing).
- `test_create_without_description`: testear que la descripción es opcional y queda `null` si no se envía.
- `test_create_duplicate_case_insensitive`: testear que `react`, `REACT` y `ReAct` chocan con `React` ya cargado (409).
- `test_create_invalid_rejected`: testear body vacío, nombre en blanco, nombre de más de 100 caracteres, descripción de más de 500 y campo desconocido (422).

**Consultar**
- `test_list_ordered_by_name`: testear que el listado se ordena por nombre.
- `test_list_q_filter`: testear el filtro `q` sobre el nombre.
- `test_list_pagination`: testear `limit`/`offset`, `total` y que `limit=0` responde 422.
- `test_get_not_found`: testear que una tecnología inexistente responde 404.

**Modificar**
- `test_patch_name_and_description`: testear que el PATCH cambia nombre (casing distinto permitido) y descripción.
- `test_patch_clear_description`: testear que `description: null` limpia el campo.
- `test_patch_name_null_rejected`: testear que `name: null` responde 422.
- `test_patch_empty_and_unknown_rejected`: testear body vacío, campo desconocido y descripción demasiado larga (422).
- `test_patch_duplicate_name_rejected`: testear que el nombre no puede chocar con el de otra tecnología sin distinguir mayúsculas (409).
- `test_patch_not_found`: testear que editar una tecnología inexistente responde 404.

**Eliminar**
- `test_delete_technology`: testear el borrado (204) y que deja de existir.
- `test_delete_not_found`: testear que eliminar una tecnología inexistente responde 404.
- `test_delete_in_use_rejected`: testear que no se puede borrar una tecnología asociada a un proyecto (409) y que sigue existiendo.

**Imagen de la tecnología**
- `test_image_endpoints_require_auth`: testear que los endpoints de imagen de la tecnología responden 401 sin login.
- `test_image_endpoints_forbidden_for_student`: testear que un alumno no puede subir ni quitar la imagen de una tecnología (403).
- `test_create_with_uploaded_image_via_json`: testear el alta con `id_image` de una imagen ya subida y que la respuesta trae el objeto imagen completo.
- `test_create_multipart_with_file`: testear el alta en multipart con `file`, normalizando el nombre y convirtiendo la imagen a WebP (guardada en disco).
- `test_create_multipart_without_file`: testear el alta en multipart sin archivo (imagen `null`).
- `test_create_multipart_missing_name`: testear que un multipart sin `name` responde 422.
- `test_create_multipart_bad_file_creates_nothing`: testear que un archivo inválido responde 422 y no deja creada la tecnología.
- `test_create_json_unknown_image_404_and_taken_409`: testear que un `id_image` inexistente responde 404 y que una imagen ya asignada a otra tecnología responde 409.
- `test_patch_multipart_file_replaces_and_deletes_previous`: testear que un PATCH con `file` reemplaza la imagen, borra la anterior (fila y disco) y responde con la nueva.
- `test_patch_json_without_image_fields_keeps_image`: testear que un PATCH sin campos de imagen conserva la imagen.
- `test_patch_null_id_image_does_not_detach`: testear que `id_image: null` no desasocia (null = no enviado).
- `test_put_route_replaces_previous_image`: testear que `PUT .../image` sube la imagen y, al repetirlo, reemplaza y borra la anterior.
- `test_delete_technology_image_route`: testear que `DELETE .../image` quita y borra la imagen (204) y que sin imagen responde 404.
- `test_delete_technology_deletes_its_image`: testear que al eliminar la tecnología también se borra su imagen.
- `test_delete_image_in_use_by_technology_rejected`: testear que `DELETE /images/{id}` responde 409 mientras la imagen esté asignada a una tecnología.
- `test_unsupported_content_type_rejected`: testear que un body que no es JSON ni multipart responde 422.
- `test_patch_json_replaces_image_and_deletes_previous`: testear que un PATCH con `id_image` reemplaza la imagen, borra la anterior (fila y disco) y responde con la nueva.
- `test_patch_json_image_taken_by_another_rejected`: testear que asignar por JSON una imagen que ya usa otra tecnología responde 409.
- `test_put_image_errors`: testear que `PUT .../image` con una tecnología inexistente responde 404 y con un archivo inválido 422.

## `tests/test_project_technologies.py`

Vínculo proyecto–tecnología: asociar (`POST /projects/{id}/technologies`), asociar en lote (`POST .../bulk`), listar (`GET /projects/{id}/technologies`) y quitar (`DELETE /projects/{id}/technologies/{id_technology}`); la gestión es para los privilegiados del proyecto mientras no esté en un estado final, y la consulta sigue la privacidad del proyecto.

**Permisos**
- `test_requires_authentication`: testear que los cuatro endpoints responden 401 sin login.
- `test_student_without_privileges_cannot_manage`: testear que un alumno sin membresía no puede asociar en forma individual ni en lote, ni quitar tecnologías (403).
- `test_unassigned_professor_cannot_manage`: testear que un profesor no asignado al curso lectivo no puede gestionar tecnologías del proyecto (403).
- `test_member_can_manage`: testear que un integrante `active` del grupo puede asociar y quitar tecnologías.
- `test_assigned_professor_can_manage`: testear que el profesor asignado al curso lectivo puede asociar y quitar tecnologías.
- `test_unknown_project`: testear que un proyecto inexistente responde 404 en los cuatro endpoints.
- `test_any_logged_user_can_list_public_project`: testear que cualquier usuario logueado puede listar las tecnologías de un proyecto `uninsured` sin integrantes.

**Agregar**
- `test_add_technology`: testear el alta individual (201) y que la tecnología queda en el listado del proyecto.
- `test_add_duplicate_rejected`: testear que una tecnología ya asociada a ese proyecto responde 409.
- `test_add_unknown_technology`: testear que una tecnología inexistente responde 404.
- `test_add_invalid_body_rejected`: testear body vacío, id inválido y campo desconocido (422).
- `test_add_allowed_while_insured_not_final`: testear que se puede asociar en un proyecto asegurado pero no final (`in_idea`).
- `test_changes_rejected_on_final_project`: testear que en un proyecto final (`approved`) responder 409 asociar en forma individual, en lote y quitar.

**Alta en lote**
- `test_bulk_add`: testear el lote feliz (201) con las tecnologías devueltas ordenadas por nombre.
- `test_bulk_all_or_nothing`: testear que una fila con id inexistente responde 422 con el detalle por fila y no se vincula ninguna tecnología (todo o nada).
- `test_bulk_duplicated_in_request`: testear que un id repetido dentro del mismo lote responde 422 con el error por fila.
- `test_bulk_already_linked`: testear que una tecnología ya asociada al proyecto responde 422 con el error por fila y que el resto del lote no se aplica.
- `test_bulk_invalid_body_rejected`: testear lista vacía, más de 100 elementos y campo desconocido (422).

**Consultar**
- `test_list_q_filter`: testear el filtro `q` sobre el nombre.
- `test_list_pagination`: testear `limit`/`offset`, `total` y que `limit=0` responde 422.
- `test_list_private_visible_only_to_privileged`: testear que en un proyecto `private` asegurado un ajeno recibe 403 y un miembro ve el listado.
- `test_list_protected_visible_to_any_user`: testear que un proyecto `protected` asegurado es visible para cualquier usuario logueado.

**Quitar**
- `test_remove_technology`: testear el quitado (204), que la tecnología queda fuera del listado del proyecto y sigue existiendo en el catálogo.
- `test_remove_not_linked`: testear que quitar una tecnología no asociada responde 404.

**Borrar el proyecto**
- `test_delete_project_cascades_links`: testear que al eliminar un proyecto (vacío y `uninsured`) sus vínculos desaparecen con él, la tecnología sobrevive y un proyecto nuevo arranca sin vínculos.

## `tests/test_seed.py`

Carga el seed real (`data/seed.json`) una sola vez por módulo y valida su volumen, relaciones y reglas del dominio. Al terminar restaura `seed_test.json` para no afectar al resto de la suite. `seed_test.json` sigue siendo el seed mínimo de los tests de recursos.

- `test_seed_key_counts`: testear los conteos clave: 4 comisiones, 10 cursos lectivos, 16 profesores, 200 alumnos, 30 asignaciones, 32 proyectos, 10 calendarios, 30 actividades, 20 tecnologías y 95 vínculos proyecto-tecnología.
- `test_seed_section_years_allow_project_joins`: testear que `allow_project_joins` está activo solo en `3K2` 2025 y `3K3` 2026.
- `test_seed_group_size_ranges_and_years`: testear que `3K4` solo existe en 2024, que los cursos lectivos son 2024-2026 y que todos los grupos tienen entre 5 y 10 miembros.
- `test_seed_three_distinct_professors_per_section_year`: testear que cada curso lectivo tiene exactamente 3 profesores distintos.
- `test_seed_projects_have_unique_group_numbers_per_section_year`: testear que los números de grupo son únicos y consecutivos por curso lectivo, con 2 a 4 grupos.
- `test_seed_projects_cover_all_states`: testear que hay al menos un proyecto en cada estado (`uninsured`, `in_idea`, `in_progress`, `pending_approval`, `rejected`, `approved` y `cancelled`).
- `test_seed_memberships_cover_all_states`: testear que hay membresías en todos los estados (`active`, `pending_approval`, `abandoned`, `finished`, `expelled` y `rejected`).
- `test_seed_privacy_values_are_valid`: testear que la privacidad de todos los proyectos es `public`, `protected` o `private`.
- `test_seed_statuses_are_loaded`: testear que quedan cargados los 13 estados base (7 de `project` y 6 de `student_project`) y sus estados finales.
- `test_seed_each_project_with_members_has_exactly_one_leader`: testear que cada proyecto con integrantes tiene exactamente un jefe.
- `test_seed_membership_statuses_are_valid_and_consistent`: testear que cada membresía tiene un estado de su ámbito y que los jefes no quedan en estados de solicitud.
- `test_seed_cancelled_projects_have_failed_cursadas`: testear que los integrantes de proyectos cancelados quedan `abandoned`/`rejected` y sus cursadas `finished_failed`.
- `test_seed_projects_and_memberships_have_status_of_their_ambito`: testear que cada proyecto tiene un estado del ámbito `project` y cada membresía del ámbito `student_project`.
- `test_seed_project_status_history_matches_current_status`: testear que cada proyecto tiene historial, que empieza con `status_from=null` y termina en su estado actual.
- `test_seed_emails_and_legajos_are_unique`: testear que no se repiten mails de profesores, legajos de profesores ni legajos de alumnos.
- `test_seed_users_are_adults`: testear que todos los usuarios del seed son mayores de edad.
- `test_seed_students_have_at_most_one_member_group`: testear que ningún alumno es `member` (`active`/`finished`) de más de un grupo en todo el sistema.
- `test_seed_all_projects_belong_to_a_section_year`: testear que todos los proyectos referencian un curso lectivo existente.
- `test_seed_users_can_log_in`: testear que Ana, el super admin y Carlos pueden loguearse con su contraseña.
- `test_seed_student_section_years_are_consistent`: testear inscripción única por alumno/año, cursada única por comisión, una sola cursada `attending` por alumno, cobertura de todos los estados y relación con las membresías.
- `test_seed_students_may_have_several_section_years`: testear que hay alumnos con más de una fila en distintos cursos lectivos.
- `test_seed_calendars_are_consistent`: testear un calendario por curso lectivo, clases dentro del año, horarios válidos, sin solapamientos y con clases en todos los calendarios.
- `test_seed_activities_are_consistent`: testear actividades dentro del año, con título y calendario válido, y al menos una por curso lectivo.
- `test_seed_technology_catalog_and_links`: testear nombres únicos sin distinguir mayúsculas y vínculos proyecto-tecnología válidos y sin duplicados.
- `test_seed_attendance_is_consistent`: testear asistencias únicas, solo sobre cursadas válidas y clases pasadas, sesiones cerradas, ~50-60% de clases con toma y que al menos el 80% de los alumnos tenga 60-100% de asistencia sobre esas clases.

## `tests/test_statuses.py`

**Permisos y lectura (`GET /statuses`)**
- `test_requires_authentication`: testear que listar estados sin login responde 401.
- `test_any_user_can_list_statuses`: testear que un alumno, un super admin y un profesor común pueden listar los 13 estados (7 de `project` y 6 de `student_project`).
- `test_list_returns_public_fields`: testear que la respuesta expone solo `id_status`, `ambito`, `code`, `name`, `description`, `is_final` e `is_insured`.

**Consultar**
- `test_filter_by_ambito`: testear el filtro `ambito`: `project` trae los 7 estados nuevos; `student_project` trae `active`, `pending_approval`, `abandoned`, `finished`, `expelled` y `rejected`.
- `test_invalid_ambito_rejected`: testear que un `ambito` fuera de los permitidos responde 422.
- `test_list_pagination`: testear `limit` y `offset`, y que `limit=0` se rechaza.

**Reglas por ámbito (jerarquía `State`)**
- `test_member_category`: testear que la categoría `member` es `active` + `finished` y que ningún otro estado de membresía pertenece.
- `test_insured_category`: testear que la categoría `insured` es `in_idea`, `in_progress`, `pending_approval` y `rejected`, que `is_insured` devuelve true solo para esos, y false para `uninsured`, `approved`, `cancelled` y los estados de membresía.
- `test_project_final_states`: testear que `approved` y `cancelled` están marcados `is_final` y no tienen transiciones.
- `test_initial_and_pending_status`: testear que el estado inicial de proyecto es `uninsured`, el de membresía es `active`, y que una membresía que se une a un grupo con jefe queda `pending_approval`.
- `test_membership_transitions`: testear que solo se permiten las transiciones de membresía documentadas y que un estado final no admite ninguna.
- `test_project_transitions`: testear la máquina de estados del proyecto (`uninsured → in_idea → in_progress → pending_approval → approved | rejected`, `rejected → in_progress`, insured → `uninsured`), que `approved` y `cancelled` no salen a ningún lado y que no se puede ir de `approved` a `cancelled`.
- `test_final_states_have_no_transitions`: testear que toda clase de estado marcada `is_final` no tiene transiciones (coherencia dato/regla).
- `test_catalog_codes_match_states`: testear que los códigos de cada catálogo de la jerarquía coinciden exactamente con los del catálogo persistido de ese ámbito y que los destinos de las transiciones existen.
- `test_default_statuses_match_state_metadata`: testear que el catálogo base (`name`, `description`, `is_final`) coincide con los metadatos de las clases de estado.
- `test_registry_maps_catalog_states`: testear que el registro `(ambito, code) → clase` resuelve cada estado del catálogo a su clase de dominio.
- `test_unknown_state_falls_back_to_base`: testear que un estado que no está en la jerarquía cae en `State`, que no admite transiciones.
- `test_membership_status_literal_matches_order`: testear que el `Literal` que valida `?status=` en `GET /students` coincide con los códigos de membresía.