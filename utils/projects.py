from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import (
    ProfessorSectionYear,
    Project,
    Section,
    SectionYear,
    StudentProject,
    User,
)
from schemas.project import ProjectBulkCreate, ProjectCreate, ProjectPublic
from utils.section_years import get_section_year


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

    def can_see_info(self, project: Project) -> bool:
        # public y protected muestran nombre, descripción, objetivo y problemática.
        # Cuando existan los campos sensibles (documentación, GitHub), se ocultan
        # acá a quien no sea is_privileged en proyectos que no sean public.
        return project.privacy != "private" or self.is_privileged(project)


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
            select(StudentProject.id_project).where(
                StudentProject.id_student == user.id_user
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
        privacy=project.privacy,
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

    project = Project(group_number=number, section_year=sy)
    db.add(project)
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
    projects = [
        Project(group_number=start + i, section_year=sy) for i in range(data.quantity)
    ]
    db.add_all(projects)
    try:
        await db.commit()
    except IntegrityError:  # otro profesor creó grupos al mismo tiempo
        await db.rollback()
        raise _conflict("Group numbers changed while creating, try again")
    return [to_public(p) for p in projects]


async def delete_project(db, access: Access, id_project: int) -> None:
    project = await get_project(db, id_project)
    _require_manager(access, project.id_section_year)

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
    *,
    id_section_year: int | None,
    year: int | None,
    id_section: int | None,
    privacy: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Project], int]:
    conditions = []
    if id_section_year is not None:
        conditions.append(Project.id_section_year == id_section_year)
    if year is not None:
        conditions.append(SectionYear.year == year)
    if id_section is not None:
        conditions.append(SectionYear.id_section == id_section)
    if privacy is not None:
        conditions.append(Project.privacy == privacy)

    on_sy = SectionYear.id_section_year == Project.id_section_year
    total = (
        await db.exec(
            select(func.count()).select_from(Project).join(SectionYear, on_sy).where(*conditions)
        )
    ).one()
    items = (
        await db.exec(
            select(Project)
            .join(SectionYear, on_sy)
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