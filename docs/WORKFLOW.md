# Cómo trabajar una historia de usuario

Este es el proceso que se sigue para cada funcionalidad nueva. Las reglas de código están en `AGENTS.md`, las plantillas en `docs/TEMPLATES.md` y los tests existentes en `docs/tests.md`. Acá solo se define **el orden y los entregables**.

Si la tarea es solo documentación o un arreglo menor, saltar los pasos que no apliquen y decirlo.

## 0. Antes de escribir código

1. Leer `docs/PROJECT.md` (dominio y permisos) y `docs/STRUCTURE.md`. Si la historia crea o cambia un recurso, leer también `docs/TEMPLATES.md`.
2. Identificar qué recursos existentes toca la historia: tablas con las que se relaciona, endpoints cuyo comportamiento cambia, permisos afectados.
3. **Si algo es ambiguo, no asumir en silencio.** Proponer valores por defecto concretos y pedir confirmación **una sola vez**, con la lista de decisiones:
   - nombres de la clase, tabla y ruta;
   - campos obligatorios y opcionales, y restricciones de unicidad;
   - quién puede crear, consultar, modificar y eliminar cada operación;
   - qué responde ante duplicados, referencias inexistentes y borrados con datos asociados;
   - efectos sobre recursos existentes (por ejemplo, un borrado que antes funcionaba y ahora da 409).
4. Si la historia es clara, avanzar sin preguntar y dejar las decisiones tomadas escritas en el resumen final.
5. No implementar nada marcado como "Pendiente" en `docs/PROJECT.md` sin que se haya definido su comportamiento.

## 1. Orden de implementación

Seguir siempre este orden, completando cada paso antes del siguiente:

| # | Paso | Dónde |
|---|---|---|
| 1 | **Modelo** | `models/<recurso>.py`. Exportarlo en `models/__init__.py` (import y `__all__`). |
| 2 | **Schemas** | `schemas/<recurso>.py`: `Create`, `Update`, `Public`, `List`, con `extra="forbid"` en los de entrada. |
| 3 | **Lógica** | `utils/<recurso>.py`: reglas de negocio, unicidad, referencias, borrado, listado. |
| 4 | **Rutas** | `routes/<recurso>.py`. Exportar el router en `routes/__init__.py`. |
| 5 | **Registro** | `index.py`: `app.include_router(...)` y la entrada en `openapi_tags`. |
| 6 | **Revisar la documentación de la API** | Ver sección siguiente. |
| 7 | **Tests** | `tests/test_<recurso>.py` y ajustes a los tests existentes que cambien. |
| 8 | **Documentar los tests** | `docs/tests.md`. |
| 9 | **Actualizar la documentación del proyecto** | `docs/PROJECT.md`, `docs/STRUCTURE.md` y `AGENTS.md` si corresponde. |
| 10 | **Verificar** | Correr toda la suite. |

Si la historia es una tabla intermedia o un caso especial (permisos que dependen del dato, operaciones masivas), usar la plantilla correspondiente de `docs/TEMPLATES.md`.

## 2. Revisar la documentación de la API

Hacerlo **después de cada funcionalidad**, no solo cuando el recurso es nuevo:

- Cada endpoint nuevo tiene `summary`, una docstring en español (quién puede usarlo, reglas, campos) y `responses` con todos los códigos de error posibles.
- El tag nuevo está en `openapi_tags` con una descripción útil para quien lee `/docs`.
- **Revisar los tags y endpoints existentes que la funcionalidad afecta** y actualizar su texto. Ejemplos:
  - un recurso nuevo que depende de otro: el `DELETE` del recurso original ahora puede responder 409 y debe decirlo;
  - un permiso que cambia (una consulta que pasa a ser abierta): actualizar la docstring y la descripción del tag;
  - una regla que se amplía (por ejemplo, nuevos campos editables).
- Que la descripción del tag siga siendo cierta, con los permisos reales de consulta y de escritura.

## 3. Tests: cubrir todo tipo de funcionalidad

El archivo de tests nuevo sigue el orden **permisos, crear, consultar, modificar, eliminar** y cubre, según aplique:

- **Autenticación y permisos:** sin login (401); cada rol sin permiso (403): alumno, profesor común, profesor no asignado; los roles que sí pueden; lecturas abiertas a cualquier usuario si corresponde.
- **Crear:** caso feliz, valores por defecto, normalización de datos, duplicados (409), referencias inexistentes (404), datos inválidos y campos desconocidos (422), valores límite.
- **Operaciones masivas:** caso feliz, todo o nada con detalle de errores, límites de cantidad, continuidad de numeración.
- **Consultar:** orden, filtros (solos y combinados), paginación (`limit`, `offset`, `limit=0` inválido), consulta por id y 404.
- **Visibilidad y datos privados:** qué ve cada rol, que nunca se expongan datos privados, que lo oculto no se filtre.
- **Modificar:** cada campo editable, que lo no enviado no cambie, mismos valores sin error, duplicados (409), 404, body vacío y campos no permitidos (422), efectos secundarios (sesiones, mails).
- **Eliminar:** caso feliz (204 y deja de existir), 404, bloqueo si está en uso (409), liberación de nombres o combinaciones, que solo se borre la relación y no los dos lados.
- **Reglas de negocio específicas** de la historia y **efectos sobre otros recursos**.

Además:
- **Actualizar los tests existentes** cuyo comportamiento cambió (por ejemplo, tests de permisos que recorrían endpoints que ahora son abiertos). No dejar tests obsoletos ni duplicados.
- Usar los helpers y fixtures de `tests/conftest.py` y `tests/helpers.py`; no repetir lógica de preparación.
- Un caso de prueba por comportamiento, con nombres descriptivos.

## 4. Documentar los tests en `docs/tests.md`

- Agregar una sección `## tests/test_<recurso>.py` con los grupos (permisos, crear, consultar, modificar, eliminar, reglas específicas).
- Cada test con una línea: `- test_nombre: testear que ...`. Describir el comportamiento, no los datos concretos del seed.
- Corregir las entradas de tests que se modificaron o eliminaron en archivos existentes.
- Actualizar el total de tests si el archivo lo indica.

## 5. Verificar

```bash
docker compose exec backend pytest -q
```

- Todos los tests deben pasar, **sin avisos**.
- Si se cambió una columna de una tabla que ya existía, avisar que hay que correr `docker compose down -v` (las tablas se crean con `create_all`).
- Si cambió `requirements.txt` o el `Dockerfile`, avisar que hay que reconstruir con `docker compose up --build -d`.
- Si un test falla, buscar la causa antes de tocar el test. Un test no se debilita para que pase.

## 6. Qué entregar al terminar

Un resumen corto con:

1. **Archivos creados y modificados**, con una línea por cada uno.
2. **Decisiones tomadas**, sobre todo las que usaron valores por defecto.
3. **Resultado de la suite:** cantidad de tests y confirmación de que no hay avisos.
4. **Pendientes o riesgos** que dejó la historia (por ejemplo, una regla que depende de una parte futura).
5. Los comandos que el usuario debe correr, si hay algo más que `pytest`.

## Reglas de convivencia

- Cambiar solo lo que la historia requiere. No refactorizar ni renombrar código no relacionado.
- No cambiar permisos, nombres de rutas ni formatos de respuesta existentes sin avisar explícitamente.
- No agregar dependencias sin decirlo y sin actualizar `requirements.txt`.
- Mantener las convenciones de `AGENTS.md` aunque otra solución parezca más corta.