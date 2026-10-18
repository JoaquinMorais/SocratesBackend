from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import (
    ProfessorSectionYear,
    Project,
    Section,
    SectionYear,
    Status,
    StudentProject,
    User,
)
from schemas.project import ProjectBulkCreate, ProjectCreate, ProjectPublic, ProjectUpdate
from utils.project_statuses import record_status_change
from utils.section_years import get_section_year
from utils.statuses import MEMBER, PROJECT, STUDENT_PROJECT, get_status
from utils.statuses import to_public as status_public


def is_uninsured(project: Project) -> bool:
    """Un proyecto `uninsured` (Desasegurado) se trata siempre como público."""
    return project.status.code == PROJECT.initial


@dataclass
class Access:
    """Qué puede hacer el usuario; se arma una vez por request."""

    is_super_admin: bool = False
    section_year_ids: set[int] = field(default_factory=set)  # cursos donde es profesor
    project_ids: set[int] = field(default_factory=set)  # proyectos donde es miembro

    def can_manage(self, id_section_year: int) -> bool:
        return self.is_super_admin or id_section_year in self.section_year_ids

    def is_privileged(self, project: Project) -> bool:
        return self.can_manage(project.id_section_year) or project.id_project in self.project_ids

    def can_see_detail(self, project: Project) -> bool:
        # public (y todo proyecto `uninsured`): el detalle es visible para todos.
        # protected y private: solo los privilegiados. Cuando existan los campos
        # sensibles (documentación, GitHub), se ocultan acá a quien no sea
        # is_privileged en proyectos que no sean public.
        return (
            project.privacy == "public"
            or is_uninsured(project)
            or self.is_privileged(project)
        )

    def can_see_project(self, project: Project) -> bool:
        # private: para el resto el proyecto no existe (no se lista y responde 403).
        # public, protected y `uninsured` se ven siempre.
        return (
            project.privacy != "private"
            or is_uninsured(project)
            or self.is_privileged(project)
        )


async def build_access(db, user: User) -> Access:
    access = Access()
    if user.professor:
        access.is_super_admin = user.professor.is_super_admin
        if not access.is_super_admin:
            rows = await db.exec(
                select(ProfessorSectionYear.id_section_year).where(
                    ProfessorSectionYear.id_professor == user.id_user
                )
            )
            access.section_year_ids = set(rows.all())
    if user.student:
        rows = await db.exec(
            select(StudentProject.id_project)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_student == user.id_user,
                Status.ambito == "student_project",
                Status.code.in_(STUDENT_PROJECT.codes_of(MEMBER)),
            )
        )
        access.project_ids = set(rows.all())
    return access


def to_public(project: Project, restricted: bool = False) -> ProjectPublic:
    sy = project.section_year
    return ProjectPublic(
        id_project=project.id_project,
        id_section_year=sy.id_section_year,
        year=sy.year,
        id_section=sy.id_section,
        section_name=sy.section.name,
        group_number=project.group_number,
        # Mientras el proyecto está `uninsured` la privacidad efectiva es `public`.
        privacy="public" if is_uninsured(project) else project.privacy,
        status=status_public(project.status),
        restricted=restricted,
        name=None if restricted else project.name,
        description=None if restricted else project.description,
        objective=None if restricted else project.objective,
        problem=None if restricted else project.problem,
    )


def _require_manager(access: Access, id_section_year: int) -> None:
    if not access.can_manage(id_section_year):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a professor of this section year or a super admin can do this",
        )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail)


async def get_project(db, id_project: int) -> Project:
    project = await db.get(Project, id_project)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


async def _is_leader(db, id_user: int, id_project: int) -> bool:
    """Si el usuario es el jefe (`is_leader`) con membresía `active` del grupo."""
    found = (
        await db.exec(
            select(StudentProject.id_student_project)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_project == id_project,
                StudentProject.id_student == id_user,
                StudentProject.is_leader == True,  # noqa: E712
                Status.ambito == "student_project",
                Status.code == "active",
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def _active_count(db, id_project: int) -> int:
    """Cantidad de integrantes `active` del grupo (el equipo vigente)."""
    return (
        await db.exec(
            select(func.count())
            .select_from(StudentProject)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_project == id_project,
                Status.ambito == "student_project",
                Status.code == "active",
            )
        )
    ).one()


async def _reject_pending_of_project(db, id_project: int) -> None:
    """Al asegurar, todas las solicitudes `pending_approval` del grupo se rechazan."""
    rows = (
        await db.exec(
            select(StudentProject)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_project == id_project,
                Status.ambito == "student_project",
                Status.code == STUDENT_PROJECT.pending,
            )
        )
    ).all()
    if not rows:
        return
    rejected = await get_status(db, "student_project", "rejected")
    for membership in rows:
        membership.status = rejected
        membership.is_leader = False
        db.add(membership)


async def _next_group_number(db, id_section_year: int) -> int:
    current = (
        await db.exec(
            select(func.max(Project.group_number)).where(
                Project.id_section_year == id_section_year
            )
        )
    ).one()
    return (current or 0) + 1


async def create_project(db, access: Access, data: ProjectCreate) -> ProjectPublic:
    sy = await get_section_year(db, data.id_section_year)
    _require_manager(access, sy.id_section_year)

    if data.group_number is not None:
        taken = (
            await db.exec(
                select(Project.id_project).where(
                    Project.id_section_year == sy.id_section_year,
                    Project.group_number == data.group_number,
                )
            )
        ).first()
        if taken is not None:
            raise _conflict("This group number already exists in that section year")
        number = data.group_number
    else:
        number = await _next_group_number(db, sy.id_section_year)

    initial_status = await get_status(db, "project", PROJECT.initial)
    project = Project(group_number=number, section_year=sy, status=initial_status)
    db.add(project)
    await db.flush()  # obtiene id_project
    await record_status_change(db, project.id_project, None, initial_status.id_status)
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas con el mismo número
        await db.rollback()
        raise _conflict("This group number already exists in that section year")
    return to_public(project)


async def create_projects_bulk(
    db, access: Access, data: ProjectBulkCreate
) -> list[ProjectPublic]:
    sy = await get_section_year(db, data.id_section_year)
    _require_manager(access, sy.id_section_year)

    start = await _next_group_number(db, sy.id_section_year)
    initial_status = await get_status(db, "project", PROJECT.initial)
    projects = [
        Project(group_number=start + i, section_year=sy, status=initial_status)
        for i in range(data.quantity)
    ]
    db.add_all(projects)
    await db.flush()  # obtiene los id_project
    for project in projects:
        await record_status_change(db, project.id_project, None, initial_status.id_status)
    try:
        await db.commit()
    except IntegrityError:  # otro profesor creó grupos al mismo tiempo
        await db.rollback()
        raise _conflict("Group numbers changed while creating, try again")
    return [to_public(p) for p in projects]


async def update_project(db, access: Access, id_project: int, data: ProjectUpdate) -> ProjectPublic:
    project = await get_project(db, id_project)
    if not access.is_privileged(project):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a professor of this section year, a super admin or a group member can edit this project",
        )
    if project.status.is_final:
        raise _conflict("A project in a final state cannot be modified")

    changes = data.model_fields_set
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")
    for field in changes:
        setattr(project, field, getattr(data, field))
    db.add(project)
    await db.commit()
    return to_public(project)


async def insure_project(db, access: Access, id_user: int, id_project: int) -> ProjectPublic:
    """Asegura un grupo: pasa de `uninsured` a un estado asegurado."""
    project = await get_project(db, id_project)
    is_leader = await _is_leader(db, id_user, id_project)
    if not (is_leader or access.can_manage(project.id_section_year)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the group leader, a professor of this section year or a super admin "
            "can insure this project",
        )
    if project.status.code != PROJECT.initial:  # solo grupos en formación
        raise _conflict("Only an uninsured project can be insured")

    count = await _active_count(db, id_project)
    sy = project.section_year
    if count < sy.min_students:
        raise _conflict(
            f"At least {sy.min_students} active members are required to insure this group"
        )
    if count > sy.max_students:
        raise _conflict(
            f"At most {sy.max_students} active members are allowed to insure this group"
        )

    if project.id_status_insured is not None:
        target = await db.get(Status, project.id_status_insured)
    else:
        target = await get_status(db, "project", "in_idea")
    if target is None or not PROJECT.can_transition(PROJECT.initial, target.code):
        raise _conflict("The remembered insured status is no longer valid")

    uninsured = project.status
    await _reject_pending_of_project(db, id_project)
    project.status = target
    db.add(project)
    await record_status_change(db, id_project, uninsured.id_status, target.id_status)
    await db.commit()
    return to_public(project)


async def delete_project(db, access: Access, id_project: int) -> None:
    project = await get_project(db, id_project)
    _require_manager(access, project.id_section_year)

    if project.status.code != PROJECT.initial:  # solo grupos en formación (uninsured)
        raise _conflict("Only an uninsured project can be deleted")

    has_students = (
        await db.exec(
            select(StudentProject.id_student_project)
            .where(StudentProject.id_project == id_project)
            .limit(1)
        )
    ).first()
    if has_students is not None:
        raise _conflict("Project has students and cannot be deleted")

    try:
        await db.delete(project)
        await db.commit()
    except IntegrityError:  # un alumno se unió justo ahora
        await db.rollback()
        raise _conflict("Project has students and cannot be deleted")


async def list_projects(
    db,
    access: Access,
    *,
    id_section_year: int | None,
    year: int | None,
    id_section: int | None,
    privacy: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Project], int]:
    conditions = []
    if not access.is_super_admin:
        # Un proyecto private solo lo ve quien tiene privilegios (miembro, profesor
        # del curso lectivo o super admin); para el resto no existe. Los proyectos
        # `uninsured` se tratan siempre como públicos.
        visible = [Project.privacy != "private", Status.code == PROJECT.initial]
        if access.section_year_ids:
            visible.append(Project.id_section_year.in_(access.section_year_ids))
        if access.project_ids:
            visible.append(Project.id_project.in_(access.project_ids))
        conditions.append(or_(*visible))
    if id_section_year is not None:
        conditions.append(Project.id_section_year == id_section_year)
    if year is not None:
        conditions.append(SectionYear.year == year)
    if id_section is not None:
        conditions.append(SectionYear.id_section == id_section)
    if privacy is not None:
        # La privacidad que se filtra es la efectiva: un `uninsured` cuenta como público.
        if privacy == "public":
            conditions.append(
                or_(Project.privacy == "public", Status.code == PROJECT.initial)
            )
        else:
            conditions.append(
                and_(Project.privacy == privacy, Status.code != PROJECT.initial)
            )

    on_sy = SectionYear.id_section_year == Project.id_section_year
    on_status = Status.id_status == Project.id_status
    total = (
        await db.exec(
            select(func.count())
            .select_from(Project)
            .join(SectionYear, on_sy)
            .join(Status, on_status)
            .where(*conditions)
        )
    ).one()
    items = (
        await db.exec(
            select(Project)
            .join(SectionYear, on_sy)
            .join(Status, on_status)
            .join(Section, Section.id_section == SectionYear.id_section)
            .where(*conditions)
            .order_by(
                col(SectionYear.year).desc(),
                col(Section.name),
                col(Project.group_number),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total