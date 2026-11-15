from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlmodel import func, select

from models import Activity, Calendar, Delivery, DeliveryComment, Professor
from models.state.delivery_comment import (
    ANNOTATION,
    ANNOTATION_KIND,
    CORRECTED_COMMENT,
    FEEDBACK_KIND,
    REQUESTED_COMMENT,
)
from schemas.delivery import DeliveryProjectSummary
from schemas.delivery_comment import (
    CommentKind,
    DeliveryCommentCreate,
    DeliveryCommentList,
    DeliveryCommentPublic,
    DeliveryCommentUpdate,
)
from schemas.professor import ProfessorResponsiblePublic
from utils.activities import get_activity, to_public as activity_public
from utils.deliveries import get_delivery
from utils.projects import get_project
from utils.state.delivery_comment import apply_comment_transition
from utils.statuses import get_status, to_public as status_public


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "You cannot access this delivery comment",
    )


def _staff_only() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can do this",
    )


def _author_only() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only the author can edit this comment",
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_staff(access, delivery) -> bool:
    return access.can_manage(delivery.project.id_section_year)


def _can_read(access, delivery) -> bool:
    return _is_staff(access, delivery) or (
        delivery.project.id_project in access.project_ids
    )


def _can_correct(access, delivery) -> bool:
    return _can_read(access, delivery)


def _require_readable(access, comment: DeliveryComment) -> None:
    delivery = comment.delivery
    if comment.kind == ANNOTATION_KIND and not _is_staff(access, delivery):
        raise _forbidden()
    if not _can_read(access, delivery):
        raise _forbidden()


def _author_public(comment: DeliveryComment) -> ProfessorResponsiblePublic:
    professor = comment.professor
    user = professor.user
    return ProfessorResponsiblePublic(
        id_professor=professor.id_professor,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
    )


def to_public(comment: DeliveryComment) -> DeliveryCommentPublic:
    delivery = comment.delivery
    project = delivery.project
    activity = delivery.activity
    return DeliveryCommentPublic(
        id_delivery_comment=comment.id_delivery_comment,
        id_delivery=comment.id_delivery,
        id_project=project.id_project,
        id_activity=activity.id_activity,
        id_section_year=activity.calendar.id_section_year,
        kind=comment.kind,
        author=_author_public(comment),
        project=DeliveryProjectSummary(
            id_project=project.id_project,
            group_number=project.group_number,
            name=project.name,
        ),
        activity=activity_public(activity),
        content=comment.content,
        status=status_public(comment.status),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        corrected_at=comment.corrected_at,
    )


async def get_comment(db, id_comment: int) -> DeliveryComment:
    comment = await db.get(DeliveryComment, id_comment)
    if comment is None:
        raise _not_found()
    return comment


async def create_comment(
    db,
    access,
    id_user: int,
    id_delivery: int,
    data: DeliveryCommentCreate,
) -> DeliveryCommentPublic:
    delivery = await get_delivery(db, id_delivery)
    if not _is_staff(access, delivery):
        raise _staff_only()

    initial_code = (
        ANNOTATION if data.kind == ANNOTATION_KIND else REQUESTED_COMMENT
    )
    professor = await db.get(Professor, id_user)
    if professor is None:
        raise _staff_only()
    comment_status = await get_status(db, "delivery_comment", initial_code)
    comment = DeliveryComment(
        id_delivery=id_delivery,
        id_professor=id_user,
        kind=data.kind,
        content=data.content,
        status=comment_status,
        delivery=delivery,
        professor=professor,
    )
    db.add(comment)
    await db.commit()
    return to_public(comment)


async def list_comments(
    db,
    access,
    id_delivery: int,
    *,
    kind: CommentKind | None,
    limit: int,
    offset: int,
) -> DeliveryCommentList:
    delivery = await get_delivery(db, id_delivery)
    if not _can_read(access, delivery):
        raise _forbidden()
    if kind == ANNOTATION_KIND and not _is_staff(access, delivery):
        raise _forbidden()

    conditions = [DeliveryComment.id_delivery == id_delivery]
    if not _is_staff(access, delivery):
        conditions.append(DeliveryComment.kind == FEEDBACK_KIND)
    elif kind is not None:
        conditions.append(DeliveryComment.kind == kind)

    total = (
        await db.exec(
            select(func.count())
            .select_from(DeliveryComment)
            .where(*conditions)
        )
    ).one()
    items = (
        await db.exec(
            select(DeliveryComment)
            .where(*conditions)
            .order_by(
                DeliveryComment.created_at.desc(),
                DeliveryComment.id_delivery_comment.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return DeliveryCommentList(
        items=[to_public(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _check_project_scope(access, project) -> None:
    if not access.can_manage(project.id_section_year):
        raise _staff_only()


def _check_activity_scope(access, activity) -> None:
    if not access.can_manage(activity.calendar.id_section_year):
        raise _staff_only()


def _check_delivery_scope(access, delivery) -> None:
    if not access.can_manage(delivery.project.id_section_year):
        raise _staff_only()


async def list_all_comments(
    db,
    access,
    *,
    kind: CommentKind | None,
    id_project: int | None,
    id_activity: int | None,
    id_delivery: int | None,
    id_professor: int | None,
    q: str | None,
    limit: int,
    offset: int,
) -> DeliveryCommentList:
    """Listado del staff con contexto de proyecto y actividad."""
    if id_project is not None:
        _check_project_scope(access, await get_project(db, id_project))
    if id_activity is not None:
        _check_activity_scope(access, await get_activity(db, id_activity))
    if id_delivery is not None:
        _check_delivery_scope(access, await get_delivery(db, id_delivery))

    conditions = []
    if kind is not None:
        conditions.append(DeliveryComment.kind == kind)
    if id_project is not None:
        conditions.append(Delivery.id_project == id_project)
    if id_activity is not None:
        conditions.append(Delivery.id_activity == id_activity)
    if id_delivery is not None:
        conditions.append(DeliveryComment.id_delivery == id_delivery)
    if id_professor is not None:
        conditions.append(DeliveryComment.id_professor == id_professor)
    if q is not None:
        q = q.strip()
        if not q:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "q cannot be blank",
            )
        conditions.append(DeliveryComment.content.ilike(f"%{q}%"))

    if not access.is_super_admin:
        if not access.section_year_ids:
            return DeliveryCommentList(
                items=[], total=0, limit=limit, offset=offset
            )
        conditions.append(
            Calendar.id_section_year.in_(access.section_year_ids)
        )

    join_conditions = (
        DeliveryComment.id_delivery == Delivery.id_delivery
    )
    total = (
        await db.exec(
            select(func.count())
            .select_from(DeliveryComment)
            .join(Delivery, join_conditions)
            .join(Activity, Activity.id_activity == Delivery.id_activity)
            .join(Calendar, Calendar.id_calendar == Activity.id_calendar)
            .where(*conditions)
        )
    ).one()
    items = (
        await db.exec(
            select(DeliveryComment)
            .join(Delivery, join_conditions)
            .join(Activity, Activity.id_activity == Delivery.id_activity)
            .join(Calendar, Calendar.id_calendar == Activity.id_calendar)
            .where(*conditions)
            .order_by(
                DeliveryComment.created_at.desc(),
                DeliveryComment.id_delivery_comment.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return DeliveryCommentList(
        items=[to_public(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_comment_public(
    db, access, id_comment: int
) -> DeliveryCommentPublic:
    comment = await get_comment(db, id_comment)
    _require_readable(access, comment)
    return to_public(comment)


async def update_comment(
    db,
    access,
    id_user: int,
    id_comment: int,
    data: DeliveryCommentUpdate,
) -> DeliveryCommentPublic:
    comment = await get_comment(db, id_comment)
    _require_readable(access, comment)
    if comment.kind == ANNOTATION_KIND:
        if not _is_staff(access, comment.delivery):
            raise _staff_only()
    else:
        if comment.id_professor != id_user:
            raise _author_only()
        if not _is_staff(access, comment.delivery):
            raise _staff_only()
        if comment.status.code != REQUESTED_COMMENT:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A corrected feedback comment cannot be edited",
            )

    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update"
        )

    comment.content = changes["content"]
    comment.updated_at = _now()
    db.add(comment)
    await db.commit()
    return to_public(comment)


async def correct_comment(
    db, access, id_comment: int
) -> DeliveryCommentPublic:
    comment = await get_comment(db, id_comment)
    _require_readable(access, comment)
    if comment.kind != FEEDBACK_KIND:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An annotation cannot change state",
        )
    if not _can_correct(access, comment.delivery):
        raise _forbidden()

    await apply_comment_transition(db, comment, CORRECTED_COMMENT)
    comment.corrected_at = _now()
    db.add(comment)
    await db.commit()
    return to_public(comment)
