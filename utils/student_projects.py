from fastapi import HTTPException, status
from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Status, Student, StudentProject, User
from schemas.student_project import StudentProjectMemberPublic, StudentProjectPublic
from utils.projects import get_project, is_uninsured
from utils.statuses import MEMBER, STUDENT_PROJECT, get_status, membership_initial_status
from utils.statuses import to_public as status_public


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail)


def _public(membership: StudentProject) -> StudentProjectPublic:
    return StudentProjectPublic(
        id_student_project=membership.id_student_project,
        id_project=membership.id_project,
        id_student=membership.id_student,
        is_leader=membership.is_leader,
        enrolled_at=membership.enrolled_at,
        status=status_public(membership.status),
    )


async def _get_membership(db, id_project: int, id_student_project: int) -> StudentProject:
    membership = await db.get(StudentProject, id_student_project)
    if not membership or membership.id_project != id_project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    return membership


async def _leader_exists(db, id_project: int, exclude_id: int | None = None) -> bool:
    conditions = [
        StudentProject.id_project == id_project,
        StudentProject.is_leader == True,  # noqa: E712
    ]
    if exclude_id is not None:
        conditions.append(StudentProject.id_student_project != exclude_id)
    found = (
        await db.exec(select(StudentProject.id_student_project).where(*conditions).limit(1))
    ).first()
    return found is not None


async def _has_member_membership(db, id_student: int, exclude_id: int | None = None) -> bool:
    """Si el alumno ya es `member` (`active`/`finished`) de algún proyecto."""
    conditions = [
        StudentProject.id_student == id_student,
        Status.ambito == "student_project",
        Status.code.in_(STUDENT_PROJECT.codes_of(MEMBER)),
    ]
    if exclude_id is not None:
        conditions.append(StudentProject.id_student_project != exclude_id)
    found = (
        await db.exec(
            select(StudentProject.id_student_project)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(*conditions)
            .limit(1)
        )
    ).first()
    return found is not None


async def _reject_other_pending(db, id_student: int, keep_id: int | None) -> None:
    """Al pasar a `member`, sus otras solicitudes `pending_approval` se rechazan."""
    conditions = [
        StudentProject.id_student == id_student,
        Status.ambito == "student_project",
        Status.code == STUDENT_PROJECT.pending,
    ]
    if keep_id is not None:
        conditions.append(StudentProject.id_student_project != keep_id)
    rows = (
        await db.exec(
            select(StudentProject)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(*conditions)
        )
    ).all()
    if not rows:
        return
    rejected = await get_status(db, "student_project", "rejected")
    for membership in rows:
        membership.status = rejected
        membership.is_leader = False
        db.add(membership)


async def join_project(
    db, id_student: int, id_project: int
) -> tuple[StudentProjectPublic, bool]:
    """El alumno se une a un grupo. Devuelve (membresía, se creó)."""
    project = await get_project(db, id_project)
    if not is_uninsured(project):  # solo se puede entrar mientras se forma
        raise _conflict("Only an uninsured project can be joined")

    existing = (
        await db.exec(
            select(StudentProject).where(
                StudentProject.id_project == id_project,
                StudentProject.id_student == id_student,
            )
        )
    ).first()

    if existing is not None:
        if existing.status.code != "rejected":
            raise _conflict("You already requested to join this project")
        membership, created = existing, False  # una solicitud rechazada se puede repetir
    else:
        membership, created = (
            StudentProject(id_student=id_student, id_project=id_project),
            True,
        )

    has_leader = await _leader_exists(db, id_project, exclude_id=membership.id_student_project)
    code = membership_initial_status(has_leader)

    if code == "active":
        if await _has_member_membership(
            db, id_student, exclude_id=membership.id_student_project
        ):
            raise _conflict("You already belong to another project")
        await _reject_other_pending(db, id_student, keep_id=membership.id_student_project)

    membership.is_leader = code == "active"
    membership.status = await get_status(db, "student_project", code)
    db.add(membership)
    try:
        await db.commit()
    except IntegrityError:  # dos uniones simultáneas (par único o jefe único)
        await db.rollback()
        raise _conflict("You already requested to join this project")
    return _public(membership), created


async def decide_membership(
    db, id_user: int, id_project: int, id_student_project: int, target: str
) -> StudentProjectPublic:
    """El jefe acepta (`active`) o rechaza (`rejected`) una solicitud."""
    await get_project(db, id_project)  # 404 si el proyecto no existe
    membership = await _get_membership(db, id_project, id_student_project)

    leader = (
        await db.exec(
            select(StudentProject.id_student_project).where(
                StudentProject.id_project == id_project,
                StudentProject.id_student == id_user,
                StudentProject.is_leader == True,  # noqa: E712
            )
        )
    ).first()
    if leader is None:
        raise _forbidden("Only the group leader can accept or reject requests")

    current = membership.status.code
    if not STUDENT_PROJECT.can_transition(current, target):
        raise _conflict(f"A membership in '{current}' cannot change to '{target}'")

    if target == "active":
        if await _has_member_membership(
            db, membership.id_student, exclude_id=membership.id_student_project
        ):
            raise _conflict("This student already belongs to another project")
        await _reject_other_pending(
            db, membership.id_student, keep_id=membership.id_student_project
        )

    membership.status = await get_status(db, "student_project", target)
    db.add(membership)
    await db.commit()
    return _public(membership)


async def _oldest_active(
    db, id_project: int, exclude_id: int | None = None
) -> StudentProject | None:
    """El integrante `active` más antiguo del grupo (candidato a jefe)."""
    conditions = [
        StudentProject.id_project == id_project,
        Status.ambito == "student_project",
        Status.code == "active",
    ]
    if exclude_id is not None:
        conditions.append(StudentProject.id_student_project != exclude_id)
    return (
        await db.exec(
            select(StudentProject)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(*conditions)
            .order_by(
                col(StudentProject.enrolled_at),
                col(StudentProject.id_student_project),
            )
            .limit(1)
        )
    ).first()


async def _finish_leader(db, membership: StudentProject, code: str) -> None:
    """Saca al integrante del grupo (`code`) y, si era jefe, promueve al sucesor."""
    was_leader = membership.is_leader
    new_status = await get_status(db, "student_project", code)
    membership.is_leader = False
    membership.status = new_status
    db.add(membership)
    await db.flush()  # libera el índice único de jefe antes de promover
    if not was_leader:
        return
    successor = await _oldest_active(
        db, membership.id_project, exclude_id=membership.id_student_project
    )
    if successor is not None:
        successor.is_leader = True
        db.add(successor)


async def abandon_membership(
    db, id_user: int, id_project: int, id_student_project: int
) -> None:
    """El propio alumno abandona su membresía `active` de un grupo `uninsured`."""
    project = await get_project(db, id_project)
    membership = await _get_membership(db, id_project, id_student_project)
    if membership.id_student != id_user:
        raise _forbidden("You can only abandon your own membership")
    if not is_uninsured(project):
        raise _conflict("Only an uninsured project allows members to leave")
    if not STUDENT_PROJECT.can_transition(membership.status.code, "abandoned"):
        raise _conflict(f"A membership in '{membership.status.code}' cannot be abandoned")
    await _finish_leader(db, membership, "abandoned")
    await db.commit()


async def expel_membership(db, access, id_project: int, id_student_project: int) -> None:
    """El profesor del curso lectivo (o super admin) expulsa a un integrante `active`."""
    project = await get_project(db, id_project)
    if not access.can_manage(project.id_section_year):
        raise _forbidden(
            "Only a professor of this section year or a super admin can expel members"
        )
    if not is_uninsured(project):
        raise _conflict("Only an uninsured project allows members to be expelled")
    membership = await _get_membership(db, id_project, id_student_project)
    if not STUDENT_PROJECT.can_transition(membership.status.code, "expelled"):
        raise _conflict(f"A membership in '{membership.status.code}' cannot be expelled")
    await _finish_leader(db, membership, "expelled")
    await db.commit()


async def transfer_leadership(
    db, id_user: int, id_project: int, id_student_project: int
) -> StudentProjectPublic:
    """El jefe delega la jefatura en otro integrante `active` (proyecto no final)."""
    project = await get_project(db, id_project)
    membership = await _get_membership(db, id_project, id_student_project)
    leader = (
        await db.exec(
            select(StudentProject).where(
                StudentProject.id_project == id_project,
                StudentProject.id_student == id_user,
                StudentProject.is_leader == True,  # noqa: E712
            )
        )
    ).first()
    if leader is None:
        raise _forbidden("Only the group leader can transfer the leadership")
    if project.status.is_final:
        raise _conflict("A project in a final state cannot change its leader")
    if membership.id_student_project == leader.id_student_project:
        raise _conflict("This member is already the group leader")
    if membership.status.code != "active":
        raise _conflict("The leadership can only be transferred to an active member")
    leader.is_leader = False
    db.add(leader)
    await db.flush()  # libera el índice único de jefe
    membership.is_leader = True
    db.add(membership)
    await db.commit()
    return _public(membership)


async def _to_member(membership: StudentProject, user: User) -> StudentProjectMemberPublic:
    return StudentProjectMemberPublic(
        id_student_project=membership.id_student_project,
        id_student=membership.id_student,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        is_leader=membership.is_leader,
        enrolled_at=membership.enrolled_at,
        status=status_public(membership.status),
    )


def _member_conditions(id_project: int, statuses: list[str]) -> list:
    conditions = [StudentProject.id_project == id_project, Status.ambito == "student_project"]
    if statuses:
        conditions.append(Status.code.in_(statuses))
    return conditions


def _member_priority():
    """Ordena por el orden del catálogo (`active`, `pending_approval`, ...)."""
    return case(
        {code: index for index, code in enumerate(STUDENT_PROJECT.order)},
        value=Status.code,
        else_=len(STUDENT_PROJECT.order),
    )


async def _member_rows(db, id_project: int, statuses: list[str], *, limit=None, offset=None):
    rows_stmt = (
        select(StudentProject, User)
        .join(Status, Status.id_status == StudentProject.id_status)
        .join(Student, Student.id_student == StudentProject.id_student)
        .join(User, User.id_user == Student.id_student)
        .where(*_member_conditions(id_project, statuses))
        .order_by(
            col(StudentProject.is_leader).desc(),
            _member_priority(),
            col(StudentProject.enrolled_at),
            col(StudentProject.id_student_project),
        )
    )
    if limit is not None:
        rows_stmt = rows_stmt.limit(limit).offset(offset or 0)
    rows = (await db.exec(rows_stmt)).all()
    return [await _to_member(membership, user) for membership, user in rows]


async def list_members(
    db,
    id_project: int,
    *,
    statuses: list[str],
    limit: int,
    offset: int,
) -> tuple[list[StudentProjectMemberPublic], int]:
    conditions = _member_conditions(id_project, statuses)
    total = (
        await db.exec(
            select(func.count())
            .select_from(StudentProject)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(*conditions)
        )
    ).one()
    items = await _member_rows(db, id_project, statuses, limit=limit, offset=offset)
    return items, total


async def list_all_members(
    db, id_project: int, *, statuses: list[str]
) -> list[StudentProjectMemberPublic]:
    """Todos los integrantes que cumplen `statuses`, sin paginar (para el overview)."""
    return await _member_rows(db, id_project, statuses)


async def get_responsible(db, id_project: int) -> StudentProjectMemberPublic | None:
    """El jefe del grupo (`is_leader`), independiente del filtro de estados."""
    row = (
        await db.exec(
            select(StudentProject, User)
            .join(Student, Student.id_student == StudentProject.id_student)
            .join(User, User.id_user == Student.id_student)
            .where(
                StudentProject.id_project == id_project,
                StudentProject.is_leader == True,  # noqa: E712
            )
        )
    ).first()
    if row is None:
        return None
    membership, user = row
    return await _to_member(membership, user)
