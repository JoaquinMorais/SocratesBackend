from fastapi import HTTPException, status
from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Project, Section, SectionYear, Status, Student, StudentProject, User
from models.state import MEMBER_CODES
from models.state.state_student_project import (
    STUDENT_PROJECT_ORDER,
    Abandoned,
    Active,
    Expelled,
    PendingApprovalMember,
    RejectedMember,
)
from schemas.me_project import MyProjectPublic
from schemas.project import ProjectOverviewPublic
from schemas.status import StatusPublic
from schemas.student import StudentGroupPublic
from schemas.student_project import StudentProjectMemberPublic, StudentProjectPublic
from utils.professor_section_years import list_section_year_professors
from utils.projects import get_project, is_uninsured, to_public as project_public
from utils.state import MembershipEffector, apply_transition
from utils.student_section_years import validate_project_year
from utils.statuses import get_status, membership_initial_status
from utils.statuses import to_public as status_public

# Membresías que son solicitudes de ingreso (mi equipo "no existe" con estas).
REQUEST_CODES = (PendingApprovalMember.code, RejectedMember.code)


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
        Status.code.in_(MEMBER_CODES),
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


async def join_project(
    db, id_student: int, id_project: int
) -> tuple[StudentProjectPublic, bool]:
    """El alumno se une a un grupo. Devuelve (membresía, se creó)."""
    project = await get_project(db, id_project)
    if not is_uninsured(project):  # solo se puede entrar mientras se forma
        raise _conflict("Only an uninsured project can be joined")
    await validate_project_year(db, id_student, project.section_year.year)

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

    if await _has_member_membership(
        db, id_student, exclude_id=membership.id_student_project
    ):
        raise _conflict("You already belong to another project; abandon it before joining another")

    has_leader = await _leader_exists(db, id_project, exclude_id=membership.id_student_project)
    code = membership_initial_status(has_leader)

    effector = MembershipEffector(db)
    if code == Active.code:
        await effector.reject_other_pending(membership)

    membership.is_leader = code == Active.code
    membership.status = await get_status(db, "student_project", code)
    db.add(membership)
    if code == Active.code:
        await effector.enter_cursada(membership)
    try:
        await db.commit()
    except IntegrityError:  # dos uniones simultáneas (par único o jefe único)
        await db.rollback()
        raise _conflict("You already requested to join this project")
    return _public(membership), created


async def add_member(
    db, access, id_project: int, id_student: int
) -> tuple[StudentProjectPublic, bool]:
    """Un profesor del curso lectivo (o super admin) añade un alumno a un grupo.

    El alumno entra siempre como `active` (y como jefe si el grupo no tenía uno);
    solo mientras el proyecto está `uninsured`. Aplica la regla de un solo
    `member` y la cascada de solicitudes pendientes.
    """
    project = await get_project(db, id_project)
    if not access.can_manage(project.id_section_year):
        raise _forbidden(
            "Only a professor of this section year or a super admin can add members"
        )
    if not is_uninsured(project):
        raise _conflict("Only an uninsured project allows members to be added")
    await validate_project_year(db, id_student, project.section_year.year)

    student = await db.get(Student, id_student)
    if not student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    existing = (
        await db.exec(
            select(StudentProject).where(
                StudentProject.id_project == id_project,
                StudentProject.id_student == id_student,
            )
        )
    ).first()

    created = False
    if existing is not None:
        if existing.status.code != RejectedMember.code:
            raise _conflict("This student already belongs to this project")
        membership, created = existing, False
    else:
        membership, created = (
            StudentProject(id_student=id_student, id_project=id_project),
            True,
        )

    if await _has_member_membership(
        db, id_student, exclude_id=membership.id_student_project
    ):
        raise _conflict("This student already belongs to another project")

    has_leader = await _leader_exists(db, id_project, exclude_id=membership.id_student_project)

    effector = MembershipEffector(db)
    await effector.reject_other_pending(membership)

    membership.is_leader = not has_leader
    membership.status = await get_status(db, "student_project", Active.code)
    db.add(membership)
    await effector.enter_cursada(membership)
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas
        await db.rollback()
        raise _conflict("This student already belongs to this project")
    return _public(membership), created


async def decide_membership(
    db, id_user: int, id_project: int, id_student_project: int, target: str
) -> StudentProjectPublic:
    """El jefe acepta (`active`) o rechaza (`rejected`) una solicitud."""
    project = await get_project(db, id_project)  # 404 si el proyecto no existe
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

    if target == Active.code:
        if await _has_member_membership(
            db, membership.id_student, exclude_id=membership.id_student_project
        ):
            raise _conflict("This student already belongs to another project")
        await validate_project_year(
            db, membership.id_student, project.section_year.year
        )

    await apply_transition(db, membership, target, effector=MembershipEffector(db))
    await db.commit()
    return _public(membership)


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
    await apply_transition(
        db, membership, Abandoned.code, effector=MembershipEffector(db)
    )
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
    await apply_transition(
        db, membership, Expelled.code, effector=MembershipEffector(db)
    )
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
    if membership.status.code != Active.code:
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
        {code: index for index, code in enumerate(STUDENT_PROJECT_ORDER)},
        value=Status.code,
        else_=len(STUDENT_PROJECT_ORDER),
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


async def get_leader(db, id_project: int) -> StudentProjectMemberPublic | None:
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


async def build_overview(
    db, project: Project, *, restricted: bool = False, statuses: list[str] | None = None
) -> ProjectOverviewPublic:
    """Proyecto + integrantes (según `statuses`), responsables y jefe."""
    members = await list_all_members(
        db, project.id_project, statuses=list(statuses) if statuses else list(MEMBER_CODES)
    )
    return ProjectOverviewPublic(
        **project_public(project, restricted=restricted).model_dump(),
        members=members,
        responsible=await list_section_year_professors(db, project.id_section_year),
        leader=await get_leader(db, project.id_project),
    )


async def get_team_membership(db, id_student: int) -> StudentProject | None:
    """La membresía `member` (`active`/`finished`) del alumno en todo el sistema.

    Si hubiera más de una (no debería, por las reglas de ingreso), toma la más
    reciente.
    """
    return (
        await db.exec(
            select(StudentProject)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_student == id_student,
                Status.ambito == "student_project",
                Status.code.in_(MEMBER_CODES),
            )
            .order_by(
                col(StudentProject.enrolled_at).desc(),
                col(StudentProject.id_student_project).desc(),
            )
            .limit(1)
        )
    ).first()


async def list_my_requests(db, id_student: int) -> list[StudentGroupPublic]:
    """Las solicitudes de ingreso del alumno (`pending_approval` y `rejected`).

    Resumen de cada grupo (comisión, año y número de grupo, estado del proyecto
    no). Orden: pendientes primero y, dentro de cada estado, de la más nueva a
    la más vieja.
    """
    rows = (
        await db.exec(
            select(
                Project.id_project,
                Project.name,
                Project.group_number,
                SectionYear.id_section_year,
                SectionYear.year,
                Section.id_section,
                Section.name,
                StudentProject.is_leader,
                Status.id_status,
                Status.ambito,
                Status.code,
                Status.name,
                Status.description,
                Status.is_final,
            )
            .join(Project, Project.id_project == StudentProject.id_project)
            .join(SectionYear, SectionYear.id_section_year == Project.id_section_year)
            .join(Section, Section.id_section == SectionYear.id_section)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_student == id_student,
                Status.ambito == "student_project",
                Status.code.in_(REQUEST_CODES),
            )
            .order_by(
                _member_priority(),
                col(StudentProject.enrolled_at).desc(),
                col(StudentProject.id_student_project).desc(),
            )
        )
    ).all()
    return [
        StudentGroupPublic(
            id_project=id_project,
            project_name=project_name,
            group_number=group_number,
            id_section_year=id_section_year,
            year=year,
            id_section=id_section,
            section_name=section_name,
            is_leader=is_leader,
            status=StatusPublic(
                id_status=id_status,
                ambito=ambito,
                code=code,
                name=name,
                description=description,
                is_final=is_final,
            ),
        )
        for (
            id_project,
            project_name,
            group_number,
            id_section_year,
            year,
            id_section,
            section_name,
            is_leader,
            id_status,
            ambito,
            code,
            name,
            description,
            is_final,
        ) in rows
    ]


async def get_my_project(db, id_student: int) -> MyProjectPublic:
    """Mi proyecto (mi equipo: membresía `member`) y mis solicitudes de ingreso."""
    membership = await get_team_membership(db, id_student)
    if membership is None:
        return MyProjectPublic(requests=await list_my_requests(db, id_student))
    project = await get_project(db, membership.id_project)
    # Siendo miembro tiene privilegios, así que el detalle no queda restringido.
    return MyProjectPublic(
        project=await build_overview(db, project, restricted=False),
        requests=await list_my_requests(db, id_student),
    )
