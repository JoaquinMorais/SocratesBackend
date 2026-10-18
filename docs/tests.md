# Tests

Ejecutar (dentro de Docker):

```bash
docker compose exec backend pytest -q
docker compose exec backend pytest -x                              # se detiene en el primer fallo
docker compose exec backend pytest tests/test_auth.py -k refresh   # solo algunos
```

## Cómo funcionan

- Cada corrida crea una BD temporal (`<nombre_bd>_test`) y la borra al terminar. La BD principal no se toca.
- La BD de test se siembra **una sola vez por sesión** (`data/seed_test.json`: Ana, Luis y Marta). Cada test corre dentro de un **savepoint** que se revierte al terminar, así que no se vuelve a truncar ni sembrar entre tests: es rápido y cada test queda aislado.
- La app y los ayudantes de los tests comparten la misma conexión (el `conftest` publica una fábrica de sesiones bindeada a la transacción de test). Por eso se ve todo lo que cada test escribe, pero nada queda entre tests.
- En tests, Argon2 usa parámetros baratos (misma lógica de auth; el hasher de producción no cambia). Esto acelera el seed y los logins.
- Los mails no se envían: quedan en una lista (`outbox`) de donde los tests leen los códigos OTP.
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
- `test_create_student_under_18_rejected`: testear que un alumno con menos de 18 años no se puede crear (422).
- `test_create_student_exactly_18_allowed`: testear que un alumno que cumple 18 años hoy sí se puede crear.

**Carga masiva**
- `test_bulk_create`: testear que se pueden crear varios alumnos en una sola request.
- `test_bulk_is_all_or_nothing`: testear que si una fila falla no se crea ninguna y el error indica el número de fila.
- `test_bulk_duplicate_inside_request`: testear que un legajo repetido dentro del mismo lote se rechaza.
- `test_bulk_student_under_18_rejected`: testear que si un alumno del lote tiene menos de 18 años se rechaza todo el lote (422).

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
- `test_list_search`: testear la búsqueda por nombre, apellido y legajo (exacto).
- `test_professor_cannot_filter_foreign_section_year`: testear que un profesor que filtra un curso lectivo que no dicta recibe 403.
- `test_list_does_not_expose_private_data`: testear que no se expone la fecha de nacimiento ni campos del detalle del proyecto, solo el id, nombre y número del grupo, los datos del curso lectivo, si el alumno es jefe y el estado de la membresía.
- `test_list_pagination`: testear `limit` y `offset`, y que `limit=0` se rechaza.

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
- `test_patch_duplicate_mail_rejected`: testear que no se puede usar el mail de otro profesor, sin distinguir mayúsculas (409).
- `test_patch_student_domain_is_reserved`: testear que no se puede poner un mail con el dominio de alumnos.
- `test_promote_and_demote_other_professor`: testear que un super admin puede dar y quitar el rol de super admin a otro profesor.
- `test_cannot_remove_own_super_admin`: testear que un super admin no puede quitarse a sí mismo el rol (409).
- `test_super_admin_edits_self`: testear que un super admin puede editar sus propios datos y conserva el rol.
- `test_patch_professor_not_found`: testear que un profesor inexistente responde 404.
- `test_patch_professor_forbidden_fields`: testear que contraseña, id y `email` no se pueden modificar (422).
- `test_patch_professor_empty_body_rejected`: testear que un body vacío se rechaza.

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
- `test_patch_max_less_than_min_rejected`: testear que dejar `max_students` por debajo de `min_students` responde 422 (enviando ambos o solo uno).
- `test_patch_min_above_max_rejected`: testear que subir `min_students` por encima del `max_students` actual responde 422.
- `test_patch_to_existing_combination_rejected`: testear que no se puede dejar la combinación de otro curso lectivo (409).
- `test_patch_same_values_is_ok`: testear que reenviar los valores actuales no da error.
- `test_patch_not_found`: testear que modificar un curso lectivo inexistente responde 404.
- `test_patch_unknown_section_rejected`: testear que cambiar a una comisión inexistente responde 404.
- `test_patch_invalid_rejected`: testear que se rechaza un body vacío, un año fuera de rango, un id no positivo, un rango de estudiantes fuera de 1-100 y campos desconocidos.

**Eliminar**
- `test_delete_section_year`: testear que se elimina (204) y luego ya no existe ni figura en el listado.
- `test_delete_not_found`: testear que eliminar un curso lectivo inexistente responde 404.
- `test_cannot_delete_section_in_use`: testear que no se puede eliminar una comisión con cursos lectivos (409) y que sí se puede después de eliminarlos.
- `test_deleted_combination_can_be_reused`: testear que la combinación de un curso lectivo eliminado vuelve a estar disponible.


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
- `test_create_assigns_next_group_number`: testear que sin `group_number` toma el siguiente libre, también después de un número explícito.
- `test_create_duplicate_group_number_rejected`: testear que no se repite el número de grupo dentro del curso lectivo (409).
- `test_same_group_number_in_other_section_year_is_ok`: testear que el mismo número puede existir en otro curso lectivo.
- `test_create_unknown_section_year`: testear que un curso lectivo inexistente responde 404.
- `test_create_invalid_rejected`: testear que se rechazan campos faltantes, ids o números no positivos y campos no permitidos (privacidad, nombre).

**Crear en masa**
- `test_bulk_create`: testear que se crean grupos consecutivos, todos con el estado inicial, y que una segunda tanda continúa la numeración.
- `test_bulk_continues_after_last_group_number`: testear que tras eliminar un grupo intermedio la numeración sigue desde el mayor.
- `test_bulk_unknown_section_year`: testear que un curso lectivo inexistente responde 404.
- `test_bulk_invalid_rejected`: testear que se rechaza una cantidad fuera de 1-50, campos faltantes y campos desconocidos.

**Consultar**
- `test_list_sorted_and_filtered`: testear el orden (año, comisión, grupo), los filtros por curso lectivo, año, comisión y privacidad (efectiva: un `uninsured` cuenta como `public`).
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
- `test_deleted_group_number_can_be_reused`: testear que un número de grupo eliminado puede volver a crearse enviándolo.
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

## `tests/test_student_projects.py`

Integrantes del proyecto: unirse a un grupo (`POST /projects/{id}/members`), aceptar/rechazar solicitudes (`PATCH /projects/{id}/members/{id_student_project}`) y listar integrantes (`GET /projects/{id}/members`).

**Permisos**
- `test_requires_authentication`: testear que unirse, listar integrantes y aceptar/rechazar sin login responden 401.
- `test_professor_cannot_join`: testear que un profesor o super admin no puede unirse a un grupo (403; solo alumnos).
- `test_non_leader_cannot_decide`: testear que un alumno que no es el jefe, un profesor y el super admin reciben 403 al aceptar o rechazar.

**Unirse**
- `test_first_member_becomes_leader_and_active`: testear que el primer integrante de un grupo vacío entra como jefe y `active`.
- `test_second_member_is_pending_and_not_leader`: testear que, si ya hay jefe, el siguiente queda `pending_approval` y no es jefe.
- `test_cannot_join_insured_project`: testear que no se puede pedir entrar a un proyecto que no está `uninsured` (409).
- `test_join_unknown_project`: testear que un proyecto inexistente responde 404.
- `test_cannot_request_twice`: testear que no se puede volver a pedir entrar si ya se es miembro o si hay una solicitud pendiente (409).
- `test_rejected_can_request_again`: testear que una solicitud `rejected` se puede volver a enviar (200) y queda `pending_approval`.
- `test_cannot_join_empty_group_when_member_elsewhere`: testear que un alumno que ya es `member` de otro grupo no puede unirse a uno vacío (sería jefe/`active`): 409.
- `test_member_can_queue_where_there_is_a_leader`: testear que un alumno `member` de un grupo sí puede solicitar entrar a otro grupo que ya tiene jefe (queda `pending_approval`).
- `test_becoming_member_rejects_other_pending`: testear que al pasar a `member`, las otras solicitudes `pending_approval` del alumno pasan a `rejected`.

**Aceptar / rechazar**
- `test_leader_accepts_request`: testear que el jefe acepta una solicitud y el alumno queda `active` (sin ser jefe).
- `test_leader_rejects_request`: testear que el jefe rechaza una solicitud y el alumno queda `rejected`.
- `test_decide_invalid_transition`: testear que una transición no permitida (por ejemplo `active → active` o `active → rejected`) responde 409.
- `test_accept_when_student_already_member`: testear que aceptar a un alumno que ya es `member` de otro grupo responde 409.
- `test_decide_membership_not_found`: testear que una membresía inexistente o de otro proyecto responde 404.
- `test_decide_invalid_body`: testear que un `status` faltante, distinto de `active`/`rejected` o un campo desconocido responden 422.

**Consultar**
- `test_outsider_cannot_list`: testear que un alumno sin privilegios sobre el proyecto no puede listar integrantes (403).
- `test_member_can_list_and_leader_is_first`: testear que un miembro lista integrantes, el jefe va primero y no se expone el mail.
- `test_staff_can_list`: testear que el profesor del curso lectivo y el super admin pueden listar integrantes.
- `test_list_unknown_project`: testear que un proyecto inexistente responde 404.
- `test_list_filter_and_pagination`: testear el filtro por `status`, `limit`/`offset` y que un `status` inválido o `limit=0` responden 422.

## `tests/test_seed.py`

Carga el seed real (`data/seed.json`) en una BD vacía y valida que quede consistente.

- `test_seed_loads_expected_counts`: testear que se cargan 4 comisiones, 7 cursos lectivos, 10 profesores, 25 alumnos, 21 asignaciones, 14 grupos y 22 membresías.
- `test_seed_group_size_ranges`: testear que las cursadas de 2025 tienen mínimo 3 y máximo 10, y las de 2026 mínimo 5 y máximo 10.
- `test_seed_three_distinct_professors_per_section_year`: testear que cada curso lectivo tiene exactamente 3 profesores distintos asignados.
- `test_seed_two_groups_per_section_year`: testear que cada curso lectivo tiene los grupos 1 y 2.
- `test_seed_privacy_values_are_valid`: testear que la privacidad de todos los proyectos es `public`, `protected` o `private`.
- `test_seed_statuses_are_loaded`: testear que quedan cargados los 13 estados base (7 de `project` y 6 de `student_project`) y que los finales son `approved`, `cancelled`, `abandoned`, `finished` y `expelled`.
- `test_seed_each_project_with_members_has_exactly_one_leader`: testear que cada grupo con alumnos tiene exactamente un jefe.
- `test_seed_membership_status_follows_leader_rule`: testear que el jefe queda `active` y los demás miembros `pending_approval`.
- `test_seed_projects_and_memberships_have_status_of_their_ambito`: testear que cada proyecto tiene un estado del ámbito `project` y cada membresía del ámbito `student_project`.
- `test_seed_every_project_has_initial_status_history`: testear que cada proyecto del seed tiene al menos un registro de historial y que el primero tiene `status_from` en `null`.
- `test_seed_emails_and_legajos_are_unique`: testear que no se repiten mails de profesores, legajos de profesores ni legajos de alumnos.
- `test_seed_users_are_adults`: testear que todos los usuarios del seed son mayores de edad.
- `test_seed_students_have_at_most_one_member_group`: testear que ningún alumno es `member` (`active`/`finished`) de más de un grupo en todo el sistema.
- `test_seed_all_projects_belong_to_a_section_year`: testear que todos los proyectos referencian un curso lectivo existente.
- `test_seed_users_can_log_in`: testear que un alumno, el super admin y un profesor común del seed pueden loguearse con su contraseña.

## `tests/test_statuses.py`

**Permisos y lectura (`GET /statuses`)**
- `test_requires_authentication`: testear que listar estados sin login responde 401.
- `test_any_user_can_list_statuses`: testear que un alumno, un super admin y un profesor común pueden listar los 13 estados (7 de `project` y 6 de `student_project`).
- `test_list_returns_public_fields`: testear que la respuesta expone solo `id_status`, `ambito`, `code`, `name`, `description`, `is_final` e `is_insured`.

**Consultar**
- `test_filter_by_ambito`: testear el filtro `ambito`: `project` trae los 7 estados nuevos; `student_project` trae `active`, `pending_approval`, `abandoned`, `finished`, `expelled` y `rejected`.
- `test_invalid_ambito_rejected`: testear que un `ambito` fuera de los permitidos responde 422.
- `test_list_pagination`: testear `limit` y `offset`, y que `limit=0` se rechaza.

**Reglas por ámbito (`StatusPolicy`)**
- `test_member_category`: testear que la categoría `member` es `active` + `finished` y que ningún otro estado de membresía pertenece.
- `test_insured_category`: testear que la categoría `insured` es `in_idea`, `in_progress`, `pending_approval` y `rejected`, que `is_insured` devuelve true solo para esos, y false para `uninsured`, `approved`, `cancelled` y los estados de membresía.
- `test_project_final_states`: testear que `approved` y `cancelled` están marcados `is_final` y no tienen transiciones.
- `test_initial_and_pending_status`: testear que el estado inicial de proyecto es `uninsured`, el de membresía es `active`, y que una membresía que se une a un grupo con jefe queda `pending_approval`.
- `test_transitions`: testear que solo se permiten las transiciones de membresía documentadas y que un estado final no admite ninguna.
- `test_project_transitions`: testear la máquina de estados del proyecto (`uninsured → in_idea → in_progress → pending_approval → approved | rejected`, `rejected → in_progress`, insured → `uninsured`), que `approved` y `cancelled` no salen a ningún lado y que no se puede ir de `approved` a `cancelled`.
- `test_final_states_have_no_transitions`: testear que todo estado marcado `is_final` en el catálogo no tiene transiciones en su política (coherencia dato/regla).
- `test_policy_codes_match_catalog`: testear que el orden y las categorías de cada política referencian exactamente los códigos del catálogo de ese ámbito.
- `test_membership_status_literal_matches_policy`: testear que el `Literal` que valida `?status=` en `GET /students` coincide con los códigos de la política de membresías.