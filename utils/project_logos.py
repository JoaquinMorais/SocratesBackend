from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from models import Image, ProjectImage
from utils import storage
from utils.images import (
    get_image,
    image_in_use,
    prepare_image,
    project_logo_in_use,
)
from utils.projects import get_project, to_public


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a privileged member or a professor of this section year can set the logo",
    )


def _final() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "A project in a final state cannot change its logo",
    )


def _logo_taken() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "Image is already the logo of another project",
    )


def _no_logo() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Project has no logo")


async def _delete_image_if_unused(db, image: Image | None) -> None:
    if image is None:
        return
    if (await db.exec(image_in_use(db, image.id_image))).first() is not None:
        return
    if (await db.exec(project_logo_in_use(db, image.id_image))).first() is not None:
        return
    await db.delete(image)
    await db.commit()
    storage.delete_file(image.key)


async def set_project_logo(
    db,
    access,
    id_project: int,
    *,
    file_data: bytes | None = None,
    file_name: str | None = None,
    id_image: int | None = None,
):
    project = await get_project(db, id_project)
    if not access.is_privileged(project):
        raise _forbidden()
    if project.status.is_final:
        raise _final()

    existing = await db.get(ProjectImage, id_project)
    if id_image is not None:
        if (await db.exec(project_logo_in_use(db, id_image, exclude_project=id_project))).first() is not None:
            raise _logo_taken()
        image = await get_image(db, id_image)
        webp = None
    elif file_data is not None:
        image, webp = await prepare_image(file_data, file_name)
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A file or id_image is required",
        )

    old_image = existing.image if existing is not None else None
    if webp is not None:
        storage.save_file(image.key, webp)
        db.add(image)
        await db.flush()

    new_link = existing or ProjectImage(id_project=id_project)
    new_link.id_image = image.id_image
    new_link.image = image
    try:
        db.add(new_link)
        project.logo = new_link
        db.add(project)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if webp is not None:
            storage.delete_file(image.key)
        raise _logo_taken()
    except Exception:
        await db.rollback()
        if webp is not None:
            storage.delete_file(image.key)
        raise

    if old_image is not None and old_image.id_image != image.id_image:
        await _delete_image_if_unused(db, old_image)
    return to_public(project)


async def remove_project_logo(db, access, id_project: int):
    project = await get_project(db, id_project)
    if not access.is_privileged(project):
        raise _forbidden()
    if project.status.is_final:
        raise _final()
    link = await db.get(ProjectImage, id_project)
    if link is None:
        raise _no_logo()
    image = link.image
    await db.delete(link)
    project.logo = None
    db.add(project)
    await db.commit()
    await _delete_image_if_unused(db, image)
    return to_public(project)
