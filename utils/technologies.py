from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Technology
from schemas.technology import (
    TechnologyCreate,
    TechnologyPublic,
    TechnologyUpdate,
)
from utils import storage
from utils.images import get_image, image_in_use, prepare_image, to_public as image_public


def to_public(technology: Technology) -> TechnologyPublic:
    return TechnologyPublic(
        id_technology=technology.id_technology,
        name=technology.name,
        description=technology.description,
        image=image_public(technology.image) if technology.image is not None else None,
    )


def _duplicate() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "A technology with this name already exists"
    )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Technology not found")


async def get_technology(db, id_technology: int) -> Technology:
    technology = await db.get(Technology, id_technology)
    if not technology:
        raise _not_found()
    return technology


async def _name_taken(db, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Technology.id_technology).where(
        func.lower(col(Technology.name)) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(Technology.id_technology != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def _check_external_image(db, id_image: int, exclude_technology: int | None = None):
    """El id de imagen debe existir (404) y no estar en otra tecnología (409)."""
    image = await get_image(db, id_image)
    taken = (await db.exec(image_in_use(db, id_image, exclude_technology=exclude_technology))).first()
    if taken is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Image is already assigned to another technology"
        )
    return image


async def _cleanup_image_object(db, image) -> None:
    """Borra una imagen desasociada (fila + archivo); best-effort tras el commit."""
    await db.delete(image)
    try:
        await db.commit()
    finally:
        storage.delete_file(image.key)


async def create_technology(
    db,
    data: TechnologyCreate,
    *,
    file_data: bytes | None = None,
    file_name: str | None = None,
) -> Technology:
    if await _name_taken(db, data.name):
        raise _duplicate()

    external = None
    uploaded, webp = None, None
    if file_data is not None:
        uploaded, webp = await prepare_image(file_data, file_name)
    elif data.id_image is not None:
        external = await _check_external_image(db, data.id_image)

    try:
        technology = Technology(name=data.name, description=data.description)
        if uploaded is not None:
            storage.save_file(uploaded.key, webp)
            db.add(uploaded)
            await db.flush()  # obtiene id_image
            technology.id_image = uploaded.id_image
            technology.image = uploaded
        elif external is not None:
            technology.id_image = external.id_image
            technology.image = external
        db.add(technology)
        await db.commit()
    except IntegrityError:  # dos altas simultáneas (el índice por lower(name))
        await db.rollback()
        if uploaded is not None:
            storage.delete_file(uploaded.key)
        raise _duplicate()
    except Exception:
        await db.rollback()
        if uploaded is not None:
            storage.delete_file(uploaded.key)
        raise
    return technology


async def update_technology(
    db,
    id_technology: int,
    data: TechnologyUpdate,
    *,
    file_data: bytes | None = None,
    file_name: str | None = None,
) -> Technology:
    technology = await get_technology(db, id_technology)
    changes = data.model_fields_set
    if not changes and file_data is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    if "name" in changes and data.name.lower() != technology.name.lower():
        if await _name_taken(db, data.name, exclude_id=id_technology):
            raise _duplicate()

    old_image = technology.image
    old_id = technology.id_image
    uploaded, webp = None, None
    if file_data is not None:
        uploaded, webp = await prepare_image(file_data, file_name)
    elif "id_image" in changes and data.id_image is not None:
        if data.id_image != old_id:
            await _check_external_image(db, data.id_image, exclude_technology=id_technology)

    for field in changes:
        if field == "id_image":
            continue  # la imagen se aplica por id_image o por archivo, abajo
        setattr(technology, field, getattr(data, field))

    try:
        if uploaded is not None:
            storage.save_file(uploaded.key, webp)
            db.add(uploaded)
            await db.flush()
            technology.id_image = uploaded.id_image
            technology.image = uploaded
        elif "id_image" in changes and data.id_image is not None and data.id_image != old_id:
            technology.id_image = data.id_image
            technology.image = await get_image(db, data.id_image) if data.id_image else None
        db.add(technology)
        await db.commit()
    except IntegrityError:  # dos cambios simultáneos al mismo nombre
        await db.rollback()
        if uploaded is not None:
            storage.delete_file(uploaded.key)
        raise _duplicate()
    except Exception:
        await db.rollback()
        if uploaded is not None:
            storage.delete_file(uploaded.key)
        raise

    # Después del commit: la imagen anterior se borra (fila + archivo).
    if old_id is not None and uploaded is not None:
        if old_image is not None:
            await _cleanup_image_object(db, old_image)
    elif old_id is not None and "id_image" in changes and data.id_image is not None and data.id_image != old_id:
        if old_image is not None:
            await _cleanup_image_object(db, old_image)
    return technology


async def set_technology_image(
    db, id_technology: int, *, file_data: bytes, file_name: str | None
) -> Technology:
    """Sube y asigna la imagen del grupo; reemplaza (y borra) la anterior."""
    technology = await get_technology(db, id_technology)
    uploaded, webp = await prepare_image(file_data, file_name)
    old_image = technology.image
    old_id = technology.id_image
    try:
        storage.save_file(uploaded.key, webp)
        db.add(uploaded)
        await db.flush()
        technology.id_image = uploaded.id_image
        technology.image = uploaded
        db.add(technology)
        await db.commit()
    except Exception:
        await db.rollback()
        storage.delete_file(uploaded.key)
        raise
    if old_image is not None:
        await _cleanup_image_object(db, old_image)
    return technology


async def remove_technology_image(db, id_technology: int) -> None:
    """Quita la imagen de la tecnología y la borra (404 si no tiene)."""
    technology = await get_technology(db, id_technology)
    image = technology.image
    if image is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Technology has no image"
        )
    technology.id_image = None
    technology.image = None
    db.add(technology)
    await db.commit()
    await _cleanup_image_object(db, image)


async def delete_technology(db, id_technology: int) -> None:
    technology = await get_technology(db, id_technology)
    image = technology.image
    try:
        await db.delete(technology)
        await db.commit()
    except IntegrityError:  # hay proyectos vinculados, la FK lo impide (RESTRICT)
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Technology is in use by a project and cannot be deleted",
        )
    if image is not None:
        await _cleanup_image_object(db, image)


async def list_technologies(
    db, *, q: str | None, limit: int, offset: int
) -> tuple[list[Technology], int]:
    conditions = []
    if q:
        conditions.append(col(Technology.name).ilike(f"%{q.strip()}%"))
    total = (
        await db.exec(select(func.count()).select_from(Technology).where(*conditions))
    ).one()
    items = (
        await db.exec(
            select(Technology)
            .where(*conditions)
            .order_by(col(Technology.name), col(Technology.id_technology))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total
