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
from schemas.project import (
    MAX_GROUP_NUMBER,
    ProjectBulkCreate,
    ProjectCreate,
    ProjectPublic,
    ProjectUpdate,
)
from models.state import MEMBER_CODES, PROJECT_INITIAL
from models.state.state_project import (
    Approved,
    Cancelled,
    InIdea,
    InProgress,
    PendingApprovalProject,
    RejectedProject,
    Uninsured,
)
from models.state.state_student_project import PendingApprovalMember, RejectedMember
from utils.project_statuses import record_status_change
from utils.section_years import get_section_year
from utils.state import ProjectEffector, apply_transition
from utils.student_section_years import student_current_row
from utils.statuses import get_status
from utils.statuses import to_public as status_public


def is_uninsured(project: Project) -> bool:
    """Un proyecto `uninsured` (Desasegurado) se trata siempre como público."""
    return project.status.code == PROJECT_INITIAL


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
        # Se cargan siempre: un super admin también puede dictar cursos y sus
        # endpoints "/me" necesitan sus asignaciones.
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
                Status.code.in_(MEMBER_CODES),
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
                Status.code == PendingApprovalMember.code,
            )
        )
    ).all()
    if not rows:
        return
    rejected = await get_status(db, "student_project", RejectedMember.code)
    for membership in rows:
        membership.status = rejected
        membership.is_leader = False
        db.add(membership)


async def _free_group_numbers(db, id_section_year: int, count: int) -> list[int]:
    rows = (
        await db.exec(
            select(Project.group_number).where(
                Project.id_section_year == id_section_year
            )
        )
    ).all()
    used = {r for r in rows}
    result: list[int] = []
    number = 1
    while len(result) < count and number <= MAX_GROUP_NUMBER:
        if number not in used:
            result.append(number)
        number += 1
    if len(result) < count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No free group numbers left in this section year",
        )
    return result


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
        number = (await _free_group_numbers(db, sy.id_section_year, 1))[0]

    initial_status = await get_status(db, "project", PROJECT_INITIAL)
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

    numbers = await _free_group_numbers(db, sy.id_section_year, data.quantity)
    initial_status = await get_status(db, "project", PROJECT_INITIAL)
    projects = [
        Project(group_number=number, section_year=sy, status=initial_status)
        for number in numbers
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
    if project.status.code != PROJECT_INITIAL:  # solo grupos en formación
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
        remembered = await db.get(Status, project.id_status_insured)
        target_code = remembered.code if remembered is not None else None
    else:
        target_code = InIdea.code
    if target_code is None or not Uninsured.can_transition_to(target_code):
        raise _conflict("The remembered insured status is no longer valid")

    await _reject_pending_of_project(db, id_project)
    previous, target = await apply_transition(
        db, project, target_code, effector=ProjectEffector(db)
    )
    await record_status_change(db, id_project, previous.id_status, target.id_status)
    await db.commit()
    return to_public(project)


async def _transition_project(
    db, access: Access, id_project: int, *, to_code: str
) -> ProjectPublic:
    """Aplica una transición de estado del proyecto y registra en el historial."""
    project = await get_project(db, id_project)
    if not access.can_manage(project.id_section_year):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a professor of this section year or a super admin can change "
            "the project status",
        )
    previous, target = await apply_transition(
        db, project, to_code, effector=ProjectEffector(db)
    )
    await record_status_change(db, id_project, previous.id_status, target.id_status)
    await db.commit()
    return to_public(project)


async def uninsure_project(db, access: Access, id_project: int) -> ProjectPublic:
    """Desasegura un grupo: insured → uninsured. Escribe la memoria del subestado."""
    return await _transition_project(db, access, id_project, to_code=Uninsured.code)


async def advance_project(db, access: Access, id_project: int) -> ProjectPublic:
    """in_idea → in_progress."""
    return await _transition_project(db, access, id_project, to_code=InProgress.code)


async def submit_project(db, access: Access, id_project: int) -> ProjectPublic:
    """in_progress → pending_approval."""
    return await _transition_project(
        db, access, id_project, to_code=PendingApprovalProject.code
    )


async def approve_project(db, access: Access, id_project: int) -> ProjectPublic:
    """pending_approval → approved. Cierra las membresías `active` como `finished`."""
    return await _transition_project(db, access, id_project, to_code=Approved.code)


async def reject_project(db, access: Access, id_project: int) -> ProjectPublic:
    """pending_approval → rejected."""
    return await _transition_project(db, access, id_project, to_code=RejectedProject.code)


async def retry_project(db, access: Access, id_project: int) -> ProjectPublic:
    """rejected → in_progress."""
    return await _transition_project(db, access, id_project, to_code=InProgress.code)


async def cancel_project(db, access: Access, id_project: int) -> ProjectPublic:
    """Cualquier no final → cancelled. Cierra las membresías `active` como `abandoned`."""
    return await _transition_project(db, access, id_project, to_code=Cancelled.code)


async def delete_project(db, access: Access, id_project: int) -> None:
    project = await get_project(db, id_project)
    _require_manager(access, project.id_section_year)

    if project.status.code != PROJECT_INITIAL:  # solo grupos en formación (uninsured)
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
    q: str | None,
    limit: int,
    offset: int,
    section_year_ids: list[int] | None = None,
) -> tuple[list[Project], int]:
    conditions = []
    if section_year_ids is not None:
        # Filtro interno (no expuesto como query param en GET /projects).
        conditions.append(Project.id_section_year.in_(section_year_ids))
    if not access.is_super_admin:
        # Un proyecto private solo lo ve quien tiene privilegios (miembro, profesor
        # del curso lectivo o super admin); para el resto no existe. Los proyectos
        # `uninsured` se tratan siempre como públicos.
        visible = [Project.privacy != "private", Status.code == PROJECT_INITIAL]
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
    if q:
        conditions.append(col(Project.name).ilike(f"%{q.strip()}%"))
    if privacy is not None:
        # La privacidad que se filtra es la efectiva: un `uninsured` cuenta como público.
        if privacy == "public":
            conditions.append(
                or_(Project.privacy == "public", Status.code == PROJECT_INITIAL)
            )
        else:
            conditions.append(
                and_(Project.privacy == privacy, Status.code != PROJECT_INITIAL)
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

async def current_section_years(db, user: User, access: Access) -> list[SectionYear]:
    """Los cursos lectivos "actuales" del usuario: los de su año actual.

    - Profesor: sus cursos asignados; puede haber varias comisiones del mismo año.
    - Alumno: su cursada `attending`; si no tiene, la última `finished_*`; si no,
      la última inscripción `registered`. Si no tiene filas, usa el curso lectivo
      de su grupo actual (membresía `active`/`finished`).
    - Sin cursos (incluido un super admin que no dicta) devuelve `[]`.

    Orden: comisión (nombre) y luego id.
    """
    ids: set[int] = set()
    if user.professor:
        ids = set(access.section_year_ids)
    elif user.student:
        current = await student_current_row(db, user.id_user)
        if current is not None:
            ids = {current.id_section_year}
        elif access.project_ids:
            # Sin filas propias, se usa el curso lectivo de su grupo actual.
            fallback = (
                await db.exec(
                    select(Project.id_section_year).where(
                        Project.id_project.in_(access.project_ids)
                    )
                )
            ).all()
            ids = set(fallback)

    if not ids:
        return []

    max_year = (
        await db.exec(
            select(func.max(SectionYear.year)).where(
                SectionYear.id_section_year.in_(ids)
            )
        )
    ).one()
    return list(
        (
            await db.exec(
                select(SectionYear)
                .join(Section, Section.id_section == SectionYear.id_section)
                .where(
                    SectionYear.id_section_year.in_(ids),
                    SectionYear.year == max_year,
                )
                .order_by(col(Section.name), col(SectionYear.id_section_year))
            )
        ).all()
    )


async def list_my_section_year_projects(
    db,
    access: Access,
    section_year_ids: list[int],
    *,
    limit: int,
    offset: int,
) -> tuple[list[Project], int]:
    """Proyectos de los cursos indicados, con la visibilidad de siempre."""
    if not section_year_ids:
        return [], 0
    return await list_projects(
        db,
        access,
        id_section_year=None,
        year=None,
        id_section=None,
        privacy=None,
        q=None,
        limit=limit,
        offset=offset,
        section_year_ids=section_year_ids,
    )
