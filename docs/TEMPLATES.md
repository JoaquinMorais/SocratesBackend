# Plantillas de código

Para agregar un recurso nuevo, copiar la plantilla y reemplazar los nombres. Los ejemplos usan `Widget` (tabla `widgets`, ruta `/widgets`) como recurso inventado con un campo `name` único. Las convenciones completas están en `AGENTS.md`.

**Reemplazos:** `Widget` → nombre de la clase, `widget` → nombre en minúsculas, `widgets` → plural, `id_widget` → clave primaria.

**Orden de trabajo:** modelo → schemas → lógica → rutas → registrar en `index.py` → tests → documentar en `docs/tests.md`.

---

## 1. Recurso simple (CRUD)

### `models/widget.py`
```python
from sqlmodel import Field, SQLModel


class Widget(SQLModel, table=True):
    __tablename__ = "widgets"

    id_widget: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=50)
```
Exportar en `models/__init__.py`: `from models.widget import Widget` y sumarlo a `__all__`.

### `schemas/widget.py`
```python
from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel


class WidgetCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    name: str = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("name cannot be blank")
        return v


class WidgetUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str | None) -> str | None:
        return None if v is None else WidgetCreate.normalize_name(v)


class WidgetPublic(SQLModel):
    id_widget: int
    name: str


class WidgetList(SQLModel):
    items: list[WidgetPublic]
    total: int
    limit: int
    offset: int
```

### `utils/widgets.py`
```python
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Widget
from schemas.widget import WidgetCreate, WidgetPublic, WidgetUpdate


def to_public(widget: Widget) -> WidgetPublic:
    return WidgetPublic(id_widget=widget.id_widget, name=widget.name)


def _duplicate() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "A widget with this name already exists")


async def get_widget(db, id_widget: int) -> Widget:
    widget = await db.get(Widget, id_widget)
    if not widget:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Widget not found")
    return widget


async def _name_taken(db, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Widget.id_widget).where(Widget.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Widget.id_widget != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def create_widget(db, data: WidgetCreate) -> Widget:
    if await _name_taken(db, data.name):
        raise _duplicate()
    widget = Widget(name=data.name)
    db.add(widget)
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas
        await db.rollback()
        raise _duplicate()
    return widget


async def update_widget(db, id_widget: int, data: WidgetUpdate) -> Widget:
    widget = await get_widget(db, id_widget)
    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    if "name" in changes and changes["name"] != widget.name:
        if await _name_taken(db, changes["name"], exclude_id=id_widget):
            raise _duplicate()
    for field, value in changes.items():
        setattr(widget, field, value)
    db.add(widget)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate()
    return widget


async def delete_widget(db, id_widget: int) -> None:
    widget = await get_widget(db, id_widget)
    try:
        await db.delete(widget)
        await db.commit()
    except IntegrityError:  # hay datos asociados (clave foránea)
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Widget is in use and cannot be deleted")


async def list_widgets(db, *, q: str | None, limit: int, offset: int) -> tuple[list[Widget], int]:
    conditions = []
    if q:
        conditions.append(col(Widget.name).ilike(f"%{q.strip()}%"))
    total = (await db.exec(select(func.count()).select_from(Widget).where(*conditions))).one()
    items = (
        await db.exec(
            select(Widget)
            .where(*conditions)
            .order_by(col(Widget.name), col(Widget.id_widget))  # el id desempata siempre
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total
```

### `routes/widgets.py`
```python
from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.widget import WidgetCreate, WidgetList, WidgetPublic, WidgetUpdate
from utils.auth import user_dependency
from utils.permissions import super_admin_dependency
from utils.widgets import (
    create_widget,
    delete_widget,
    get_widget,
    list_widgets,
    to_public,
    update_widget,
)

widgets_router = APIRouter(prefix="/widgets", tags=["widgets"])

_READ_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}
_WRITE_ERRORS = {
    **_READ_ERRORS,
    403: {"description": "El usuario no es profesor super admin"},
}
_NOT_FOUND = {404: {"description": "No existe el widget"}}


@widgets_router.post(
    "",
    response_model=WidgetPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un widget",
    responses={
        **_WRITE_ERRORS,
        409: {"description": "Ya existe un widget con ese nombre"},
        422: {"description": "Datos inválidos o campos desconocidos"},
    },
)
async def create_widget_route(data: WidgetCreate, db: db_dependency, _: super_admin_dependency):
    """
    Crea un widget. **Solo super admin.**

    Explicar acá las reglas: normalización, unicidad, límites, efectos secundarios.
    """
    return to_public(await create_widget(db, data))


@widgets_router.get(
    "",
    response_model=WidgetList,
    summary="Listar widgets",
    responses=_READ_ERRORS,
)
async def get_widgets(
    db: db_dependency,
    _: user_dependency,
    q: Annotated[str | None, Query(min_length=1, max_length=50, description="Busca dentro del nombre")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los widgets ordenados por nombre. **Cualquier usuario logueado.**

    Está paginado: `total` es la cantidad que cumple el filtro.
    """
    items, total = await list_widgets(db, q=q, limit=limit, offset=offset)
    return WidgetList(items=[to_public(w) for w in items], total=total, limit=limit, offset=offset)


@widgets_router.get(
    "/{id_widget}",
    response_model=WidgetPublic,
    summary="Consultar un widget",
    responses={**_READ_ERRORS, **_NOT_FOUND},
)
async def get_widget_route(id_widget: int, db: db_dependency, _: user_dependency):
    """Devuelve un widget por su id. **Cualquier usuario logueado.**"""
    return to_public(await get_widget(db, id_widget))


@widgets_router.patch(
    "/{id_widget}",
    response_model=WidgetPublic,
    summary="Modificar un widget",
    responses={
        **_WRITE_ERRORS,
        **_NOT_FOUND,
        409: {"description": "Ya existe otro widget con ese nombre"},
        422: {"description": "Body vacío, datos inválidos o campos desconocidos"},
    },
)
async def update_widget_route(
    id_widget: int, data: WidgetUpdate, db: db_dependency, _: super_admin_dependency
):
    """Modifica un widget. **Solo super admin.** Se envían solo los campos que cambian."""
    return to_public(await update_widget(db, id_widget, data))


@widgets_router.delete(
    "/{id_widget}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un widget",
    responses={
        **_WRITE_ERRORS,
        **_NOT_FOUND,
        409: {"description": "El widget está en uso y no se puede eliminar"},
    },
)
async def delete_widget_route(id_widget: int, db: db_dependency, _: super_admin_dependency):
    """Elimina un widget. **Solo super admin.** Responde 409 si tiene datos asociados."""
    await delete_widget(db, id_widget)
```

### Registrar
- `routes/__init__.py`: `from routes.widgets import widgets_router` y sumarlo a `__all__`.
- `index.py`: `app.include_router(widgets_router)` y una línea en `openapi_tags`:
  ```python
  {"name": "widgets", "description": "Descripción corta del recurso y sus permisos."},
  ```

### `tests/test_widgets.py` (esqueleto)
```python
from tests.helpers import STUDENT, SUPER_ADMIN

READ = [("GET", "/widgets", None), ("GET", "/widgets/1", None)]
WRITE = [
    ("POST", "/widgets", {"name": "A"}),
    ("PATCH", "/widgets/1", {"name": "B"}),
    ("DELETE", "/widgets/1", None),
]
ENDPOINTS = READ + WRITE


async def _create(client, headers, name: str) -> dict:
    r = await client.post("/widgets", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- permisos ----------
async def test_requires_authentication(client):
    for method, url, body in ENDPOINTS:
        r = await client.request(method, url, json=body)
        assert r.status_code == 401, (method, url)


async def test_student_cannot_write(client, login):
    headers = await login(STUDENT)
    for method, url, body in WRITE:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_regular_professor_cannot_write(client, login, make_professor):
    headers = await login(await make_professor("prof@frc.utn.edu.ar"))
    for method, url, body in WRITE:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_any_user_can_read(client, login):
    created = await _create(client, await login(SUPER_ADMIN), "A")
    headers = await login(STUDENT)
    assert (await client.get("/widgets", headers=headers)).json()["total"] == 1
    one = await client.get(f"/widgets/{created['id_widget']}", headers=headers)
    assert one.status_code == 200 and one.json() == created


# ---------- crear ----------
async def test_create_widget(client, login):
    r = await client.post("/widgets", json={"name": " a "}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 201 and r.json()["name"] == "A"


async def test_create_duplicate_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    await _create(client, headers, "A")
    r = await client.post("/widgets", json={"name": "a"}, headers=headers)
    assert r.status_code == 409


async def test_create_invalid_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    for body in ({}, {"name": ""}, {"name": "A" * 51}, {"name": "A", "extra": 1}):
        r = await client.post("/widgets", json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- consultar ----------
async def test_list_pagination(client, login):
    headers = await login(SUPER_ADMIN)
    for name in ("A", "B", "C"):
        await _create(client, headers, name)
    page1 = (await client.get("/widgets?limit=2", headers=headers)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 3
    page2 = (await client.get("/widgets?limit=2&offset=2", headers=headers)).json()
    assert len(page2["items"]) == 1
    assert (await client.get("/widgets?limit=0", headers=headers)).status_code == 422


async def test_get_not_found(client, login):
    assert (await client.get("/widgets/999", headers=await login(SUPER_ADMIN))).status_code == 404


# ---------- modificar ----------
async def test_patch_widget(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "A")
    r = await client.patch(f"/widgets/{created['id_widget']}", json={"name": "b"}, headers=headers)
    assert r.status_code == 200 and r.json()["name"] == "B"


async def test_patch_empty_body_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "A")
    r = await client.patch(f"/widgets/{created['id_widget']}", json={}, headers=headers)
    assert r.status_code == 422


async def test_patch_to_existing_name_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    await _create(client, headers, "A")
    other = await _create(client, headers, "B")
    r = await client.patch(f"/widgets/{other['id_widget']}", json={"name": "a"}, headers=headers)
    assert r.status_code == 409


# ---------- eliminar ----------
async def test_delete_widget(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "A")
    url = f"/widgets/{created['id_widget']}"
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.get(url, headers=headers)).status_code == 404


async def test_delete_not_found(client, login):
    assert (await client.delete("/widgets/999", headers=await login(SUPER_ADMIN))).status_code == 404
```

Documentar los tests en `docs/tests.md` con la forma "testear que...".

---

## 2. Tabla intermedia (muchos a muchos)

Ejemplo: `AWidgetBWidget` relaciona `Widget` con `Gadget`. Es el patrón de `ProfessorSectionYear`.

### Modelo
```python
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.gadget import Gadget
from models.widget import Widget


class WidgetGadget(SQLModel, table=True):
    __tablename__ = "widget_gadgets"
    __table_args__ = (UniqueConstraint("id_widget", "id_gadget", name="uq_widget_gadget"),)

    id_widget_gadget: int | None = Field(default=None, primary_key=True)  # id propio, a propósito
    id_widget: int = Field(foreign_key="widgets.id_widget", index=True)
    id_gadget: int = Field(foreign_key="gadgets.id_gadget", index=True)

    widget: Widget = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    gadget: Gadget = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
```
Con id propio (y no clave compuesta) la asignación se puede modificar con `PATCH` y se le pueden sumar atributos después (estado, rol, etc.).

### Reglas de la lógica (`utils/widget_gadgets.py`)
- **Crear:** verificar que existan ambos lados (404 si no) y que el par no exista (409); capturar `IntegrityError` → 409.
- **Modificar:** ambos campos opcionales; al menos uno (si no, 422); recalcular el par resultante, 404 si el nuevo lado no existe, 409 si el par ya existe (excluyendo el propio id); reenviar los mismos valores no da error.
- **Eliminar:** borra solo la relación, nunca los dos lados.
- **Listar:** filtros por cada lado, orden determinista, `to_public` que aplana los datos de ambos lados (sin datos privados).
- **Referencia cruzada:** al agregar esta tabla, los `DELETE` de `Widget` y `Gadget` ya devuelven 409 si hay relaciones (por la clave foránea); actualizar sus descripciones y agregar un test.

### Tests mínimos
Permisos (401/403/lectura abierta si corresponde), crear, duplicado (409), muchos a muchos real (un lado con varios del otro y viceversa), referencias inexistentes (404), listar con filtros, modificar (cada lado, par existente 409, mismos valores ok), eliminar (la relación se va, los dos lados siguen), y que no se pueda borrar un lado en uso.

---

## 3. Permisos que dependen del dato

Cuando el permiso no es solo un rol (por ejemplo, "profesor asignado a ese curso lectivo"), seguir el patrón de `utils/projects.py`:

```python
@dataclass
class Access:
    is_super_admin: bool = False
    section_year_ids: set[int] = field(default_factory=set)

    def can_manage(self, id_section_year: int) -> bool:
        return self.is_super_admin or id_section_year in self.section_year_ids


async def build_access(db, user) -> Access:
    ...  # una sola consulta por request, no una por proyecto
```

- Armar el `Access` una vez por request y pasarlo a la lógica.
- Combinar con `professor_dependency` en la ruta para rechazar a los alumnos antes (403).
- En listados, calcular la visibilidad por elemento con ese mismo objeto, nunca con una consulta por fila.

---

## 4. Checklist de revisión

- [ ] El modelo está exportado en `models/__init__.py` y el router en `routes/__init__.py`.
- [ ] El router está registrado en `index.py`, con su tag en `openapi_tags`.
- [ ] Los schemas de entrada usan `extra="forbid"`.
- [ ] Hay chequeo previo de unicidad **y** captura de `IntegrityError`.
- [ ] Las referencias inexistentes responden 404 y los borrados con dependencias responden 409.
- [ ] Cada endpoint tiene `summary`, docstring en español y `responses` completos.
- [ ] Ninguna respuesta incluye datos privados.
- [ ] Hay tests de permisos, caso feliz, duplicado, 404, 422 y borrado.
- [ ] `docs/tests.md` está actualizado, y también `docs/PROJECT.md` / `docs/STRUCTURE.md` si corresponde.