import json
from datetime import date
from pathlib import Path

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import (
    Professor,
    ProfessorSectionYear,
    Project,
    Section,
    SectionYear,
    Status,
    Student,
    StudentProject,
    User,
)
from utils.statuses import (
    INITIAL_STATUS,
    ensure_statuses,
    membership_initial_status,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_SEED_PATH = DATA_DIR / "seed.json"


def _build_user(item: dict) -> User:
    user = User(
        first_name=item["first_name"],
        last_name=item["last_name"],
        legajo=item["legajo"],
        birth_date=date.fromisoformat(item["birth_date"]),
    )
    if item.get("password"):
        user.set_password(item["password"])
    return user


def _missing(entity: str, value: object) -> ValueError:
    return ValueError(f"Seed: no existe {entity} para {value!r}")


async def _load_users(session: AsyncSession, data: dict) -> tuple[dict, dict]:
    """Crea alumnos y profesores; devuelve índices por legajo y por mail."""
    students: dict[int, Student] = {}
    for item in data.get("students", []):
        user = _build_user(item)
        session.add(user)
        await session.flush()  # obtiene id_user
        student = Student(id_student=user.id_user, enrollment_year=item["enrollment_year"])
        session.add(student)
        students[item["legajo"]] = student

    professors: dict[str, Professor] = {}
    for item in data.get("professors", []):
        user = _build_user(item)
        session.add(user)
        await session.flush()
        mail = item["mail"].strip().lower()
        professor = Professor(
            id_professor=user.id_user,
            mail=mail,
            is_super_admin=item.get("is_super_admin", False),
        )
        session.add(professor)
        professors[mail] = professor

    await session.flush()
    return students, professors


async def _load_sections(session: AsyncSession, data: dict) -> dict[str, Section]:
    sections: dict[str, Section] = {}
    for item in data.get("sections", []):
        section = Section(name=item["name"])
        session.add(section)
        sections[item["name"]] = section
    await session.flush()
    return sections


async def _load_section_years(
    session: AsyncSession, data: dict, sections: dict[str, Section]
) -> dict[tuple[str, int], SectionYear]:
    section_years: dict[tuple[str, int], SectionYear] = {}
    for item in data.get("section_years", []):
        name = item["section"]
        section = sections.get(name)
        if section is None:
            raise _missing("la comisión", name)
        sy = SectionYear(
            year=item["year"],
            id_section=section.id_section,
            min_students=item["min_students"],
            max_students=item["max_students"],
        )
        session.add(sy)
        section_years[(name, item["year"])] = sy
    await session.flush()
    return section_years


async def _load_professor_section_years(
    session: AsyncSession,
    data: dict,
    professors: dict[str, Professor],
    section_years: dict[tuple[str, int], SectionYear],
) -> None:
    for item in data.get("professor_section_years", []):
        professor = professors.get(item["professor"].strip().lower())
        if professor is None:
            raise _missing("el profesor", item["professor"])
        key = (item["section"], item["year"])
        sy = section_years.get(key)
        if sy is None:
            raise _missing("el curso lectivo", key)
        session.add(
            ProfessorSectionYear(
                id_professor=professor.id_professor,
                id_section_year=sy.id_section_year,
            )
        )
    await session.flush()


async def _load_projects(
    session: AsyncSession,
    data: dict,
    section_years: dict[tuple[str, int], SectionYear],
    statuses: dict[tuple[str, str], Status],
) -> dict[tuple[str, int, int], Project]:
    projects: dict[tuple[str, int, int], Project] = {}
    for item in data.get("projects", []):
        key = (item["section"], item["year"])
        sy = section_years.get(key)
        if sy is None:
            raise _missing("el curso lectivo", key)
        status = statuses.get(("project", item.get("status", INITIAL_STATUS["project"])))
        if status is None:
            raise _missing("el estado", item.get("status"))
        project = Project(
            id_section_year=sy.id_section_year,
            group_number=item["group_number"],
            privacy=item["privacy"],
            status=status,
            name=item.get("name"),
            description=item.get("description"),
            objective=item.get("objective"),
            problem=item.get("problem"),
        )
        session.add(project)
        projects[(item["section"], item["year"], item["group_number"])] = project
    await session.flush()
    return projects


def _leader_counts(items: list[dict]) -> dict[tuple[str, int, int], int]:
    """Cuenta los jefes por proyecto y falla si alguno tiene más de uno."""
    counts: dict[tuple[str, int, int], int] = {}
    for item in items:
        if item.get("is_leader", False):
            key = (item["section"], item["year"], item["group_number"])
            counts[key] = counts.get(key, 0) + 1
    for key, count in counts.items():
        if count > 1:
            raise ValueError(f"Seed: el proyecto {key} tiene más de un jefe")
    return counts


async def _load_student_projects(
    session: AsyncSession,
    data: dict,
    students: dict[int, Student],
    projects: dict[tuple[str, int, int], Project],
    statuses: dict[tuple[str, str], Status],
) -> None:
    items = data.get("student_projects", [])
    leaders = {key for key, count in _leader_counts(items).items() if count}
    for item in items:
        student = students.get(item["student"])
        if student is None:
            raise _missing("el alumno", item["student"])
        key = (item["section"], item["year"], item["group_number"])
        project = projects.get(key)
        if project is None:
            raise _missing("el proyecto", key)
        is_leader = bool(item.get("is_leader", False))
        code = item.get("status") or membership_initial_status(
            has_leader=key in leaders and not is_leader
        )
        status = statuses.get(("student_project", code))
        if status is None:
            raise _missing("el estado", code)
        session.add(
            StudentProject(
                id_student=student.id_student,
                id_project=project.id_project,
                status=status,
                is_leader=is_leader,
            )
        )
    await session.flush()


async def load_seed(session: AsyncSession, seed_path: Path | None = None) -> None:
    # Los estados son la base de proyectos y membresías: se aseguran siempre,
    # exista o no la seed (más adelante la seed puede sumar los suyos).
    statuses = await ensure_statuses(session)

    existing = (await session.exec(select(User.id_user).limit(1))).first()
    if existing is not None:
        await session.commit()
        return

    path = Path(seed_path) if seed_path is not None else DEFAULT_SEED_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    statuses = await ensure_statuses(session, data.get("statuses", []))

    students, professors = await _load_users(session, data)
    sections = await _load_sections(session, data)
    section_years = await _load_section_years(session, data, sections)
    await _load_professor_section_years(session, data, professors, section_years)
    projects = await _load_projects(session, data, section_years, statuses)
    await _load_student_projects(session, data, students, projects, statuses)

    await session.commit()
