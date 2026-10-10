# Tests

Ejecutar (dentro de Docker):

```bash
docker compose exec backend pytest -q
docker compose exec backend pytest -x                              # se detiene en el primer fallo
docker compose exec backend pytest tests/test_auth.py -k refresh   # solo algunos
```

## Cómo funcionan

- Cada corrida crea una BD temporal (`<nombre_bd>_test`) y la borra al terminar. La BD principal no se toca.
- Antes de cada test se vacían las tablas y se recarga el seed (Ana, Luis y Marta).
- Los mails no se envían: quedan en una lista (`outbox`) de donde los tests leen los códigos OTP.
- `httpx` llama a la app directamente y conserva las cookies como un navegador.

## Archivos de apoyo

| Archivo | Para qué sirve |
|---|---|
| `tests/conftest.py` | Crea y borra la BD de test, limpia las tablas entre tests, intercepta los mails y define las fixtures `client`, `login` y `make_professor`. |
| `tests/helpers.py` | Constantes del seed y utilidades: leer el código OTP del mail, leer la cookie de refresh y completar el flujo de contraseña. |

## `tests/test_auth.py`

**Login**
- `test_login_student`: testear que un alumno con contraseña puede loguearse, que el refresh token viaja solo por cookie HttpOnly y no en el JSON.
- `test_login_professor`: testear que un profesor puede loguearse con su mail.
- `test_login_invalid`: testear que se rechaza (401) contraseña incorrecta, legajo inexistente, legajo suelto sin dominio y mail desconocido.

**Perfil (`GET /me`)**
- `test_me_student`: testear que un alumno ve su rol, su mail calculado por legajo y que no se le muestra `is_super_admin`.
- `test_me_super_admin`: testear que Marta figura como profesora y super admin.
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

**Consultar usuarios (`GET /users`)**
- `test_list_requires_authentication`: testear que sin login responde 401.
- `test_student_cannot_list_users`: testear que un alumno no puede listar usuarios (403).
- `test_regular_professor_cannot_list_users`: testear que un profesor que no es super admin no puede listar (403).
- `test_super_admin_lists_users`: testear que un super admin ve todos los usuarios ordenados por apellido.
- `test_list_exposes_only_public_data`: testear que nunca se expone contraseña ni fecha de nacimiento, que los alumnos no muestran `is_super_admin` y los profesores no muestran año de ingreso.
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

**Carga masiva**
- `test_bulk_create`: testear que se pueden crear varios alumnos en una sola request.
- `test_bulk_is_all_or_nothing`: testear que si una fila falla no se crea ninguna y el error indica el número de fila.
- `test_bulk_duplicate_inside_request`: testear que un legajo repetido dentro del mismo lote se rechaza.

**Modificar un alumno (`PATCH /students/{id}`)**
- `test_patch_requires_authentication`: testear que sin login responde 401.
- `test_student_cannot_patch_students`: testear que un alumno no puede editar alumnos (403).
- `test_professor_edits_student`: testear que un profesor común edita nombre, fecha de nacimiento y año de ingreso, y que lo no enviado no cambia.
- `test_legajo_change_updates_login_mail`: testear que cambiar el legajo cambia el mail de login, conserva la contraseña y el mail viejo deja de servir.
- `test_patch_duplicate_legajo_rejected`: testear que no se puede usar el legajo de otro alumno (409).
- `test_patch_same_legajo_is_ok`: testear que reenviar el propio legajo no da error.
- `test_student_legajo_may_match_a_professor`: testear que el legajo de un alumno puede coincidir con el de un profesor.
- `test_patch_student_not_found`: testear que un alumno inexistente responde 404.
- `test_patch_student_forbidden_fields`: testear que mail, `is_super_admin` y contraseña no se pueden modificar (422).
- `test_patch_student_empty_body_rejected`: testear que un body vacío se rechaza.
- `test_patch_student_invalid_values_rejected`: testear que se rechaza un año de ingreso fuera de rango y un legajo no positivo.

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
- `test_legajo_can_repeat`: testear que el legajo de un profesor puede coincidir con el de otro usuario.

**Flujo de cuenta**
- `test_created_professor_sets_password_and_logs_in`: testear que un profesor recién creado crea su contraseña por OTP y luego puede loguearse.

**Modificar un profesor (`PATCH /professors/{id}`)**
- `test_patch_requires_authentication`: testear que sin login responde 401.
- `test_student_cannot_patch_professors`: testear que un alumno no puede editar profesores (403).
- `test_regular_professor_cannot_patch_professors`: testear que un profesor que no es super admin no puede editar profesores (403).
- `test_super_admin_edits_professor`: testear que un super admin edita nombre, legajo y mail, y que el mail se guarda en minúsculas.
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
- `test_create_section_year`: testear que se crea un curso lectivo y la respuesta incluye el nombre de la comisión.
- `test_create_duplicate_rejected`: testear que no se puede repetir la combinación año + comisión (409).
- `test_same_section_other_year_and_same_year_other_section_are_ok`: testear que una comisión puede repetirse en otro año y un año en otra comisión.
- `test_create_unknown_section_rejected`: testear que una comisión inexistente responde 404.
- `test_create_invalid_rejected`: testear que se rechaza un año fuera de rango, campos faltantes, un id no positivo y campos desconocidos.

**Consultar**
- `test_list_sorted_by_year_desc_then_section`: testear que el listado ordena por año más reciente y luego por nombre de comisión.
- `test_list_filters_and_pagination`: testear los filtros por año y comisión, `limit` y `offset`, y que `limit=0` se rechaza.
- `test_get_section_year`: testear que se puede consultar un curso lectivo por id.
- `test_get_not_found`: testear que un curso lectivo inexistente responde 404.

**Modificar**
- `test_patch_year`: testear que se puede cambiar el año y la comisión no cambia.
- `test_patch_section`: testear que se puede cambiar la comisión y el año no cambia.
- `test_patch_to_existing_combination_rejected`: testear que no se puede dejar la combinación de otro curso lectivo (409).
- `test_patch_same_values_is_ok`: testear que reenviar los valores actuales no da error.
- `test_patch_not_found`: testear que modificar un curso lectivo inexistente responde 404.
- `test_patch_unknown_section_rejected`: testear que cambiar a una comisión inexistente responde 404.
- `test_patch_invalid_rejected`: testear que se rechaza un body vacío, un año fuera de rango, un id no positivo y campos desconocidos.

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