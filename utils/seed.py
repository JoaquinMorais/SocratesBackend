import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import (
    Activity,
    Calendar,
    CalendarClass,
    Professor,
    ProfessorSectionYear,
    Project,
    ProjectStatus,
    Section,
    SectionYear,
    Status,
    Student,
    StudentProject,
    StudentSectionYear,
    User,
)
from models.state import PROJECT_INITIAL
from models.state.state_project import Approved, Cancelled
from models.state.state_student_project import (
    Abandoned,
    Expelled,
    Finished,
    PendingApprovalMember,
    RejectedMember,
)
from models.student_section_year import (
    ABANDONED,
    ATTENDING,
    FINISHED_APPROVED,
    FINISHED_FAILED,
    REGISTERED,
)
from utils.statuses import (
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
    for sy in section_years.values():
        session.add(Calendar(id_section_year=sy.id_section_year))
    await session.flush()
    return section_years


async def _load_activities(
    session: AsyncSession,
    data: dict,
    section_years: dict[tuple[str, int], SectionYear],
    calendars: dict[int, Calendar],
) -> None:
    for item in data.get("activities", []):
        key = (item["section"], item["year"])
        sy = section_years.get(key)
        if sy is None:
            raise _missing("el curso lectivo", key)
        calendar = calendars[sy.id_section_year]
        due_time = (
            time.fromisoformat(item["due_time"]) if item.get("due_time") else None
        )
        session.add(
            Activity(
                id_calendar=calendar.id_calendar,
                title=item["title"],
                description=item.get("description"),
                due_date=date.fromisoformat(item["due_date"]),
                due_time=due_time,
            )
        )
    await session.flush()


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


async def _load_calendar_classes(
    session: AsyncSession,
    data: dict,
    section_years: dict[tuple[str, int], SectionYear],
    calendars: dict[int, Calendar],
) -> None:
    for item in data.get("calendar_class_series", []):
        key = (item["section"], item["year"])
        sy = section_years.get(key)
        if sy is None:
            raise _missing("el curso lectivo", key)
        calendar = calendars[sy.id_section_year]
        from_date = date.fromisoformat(item["from"])
        to_date = date.fromisoformat(item["to"])
        day = from_date
        while day <= to_date:
            if day.isoweekday() == item["weekday"]:
                session.add(
                    CalendarClass(
                        id_calendar=calendar.id_calendar,
                        date=day,
                        start_time=time.fromisoformat(item["start_time"]),
                        end_time=time.fromisoformat(item["end_time"]),
                        modality=item.get("modality", "in_person"),
                        title=item.get("title"),
                        location=item.get("location"),
                        meeting_url=item.get("meeting_url"),
                    )
                )
            day += timedelta(days=1)
    await session.flush()


async def _load_student_section_years(
    session: AsyncSession,
    data: dict,
    students: dict[int, Student],
    section_years: dict[tuple[str, int], SectionYear],
) -> None:
    for item in data.get("student_section_years", []):
        student = students.get(item["student"])
        if student is None:
            raise _missing("el alumno", item["student"])
        key = (item["section"], item["year"])
        sy = section_years.get(key)
        if sy is None:
            raise _missing("el curso lectivo", key)
        session.add(
            StudentSectionYear(
                id_student=student.id_student,
                id_section_year=sy.id_section_year,
                year=sy.year,
                state=REGISTERED,
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
        status = statuses.get(("project", item.get("status", PROJECT_INITIAL)))
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
        await session.flush()  # obtiene id_project
        session.add(
            ProjectStatus(
                id_project=project.id_project,
                id_status_from=None,
                id_status_to=status.id_status,
            )
        )
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
        enrollment: dict = {}
        if item.get("enrolled_at"):
            enrollment["enrolled_at"] = datetime.fromisoformat(item["enrolled_at"])
        session.add(
            StudentProject(
                id_student=student.id_student,
                id_project=project.id_project,
                status=status,
                is_leader=is_leader,
                **enrollment,
            )
        )
    await session.flush()


_CURSADA_PRIORITY = {
    ATTENDING: 4,
    FINISHED_APPROVED: 3,
    FINISHED_FAILED: 2,
    ABANDONED: 1,
}


async def _load_student_cursadas(session: AsyncSession) -> None:
    """Deriva las cursadas de las membresías de los proyectos del seed.

    Las filas `student_section_years` del JSON son inscripciones; la cursada se
    crea solo al integrar un proyecto. Si el alumno tuvo más de una membresía en
    la misma comisión, se conserva el estado más relevante (la cursada actual
    gana sobre una abandonada o finalizada).
    """
    rows = (
        await session.exec(
            select(StudentProject, Project).join(
                Project, Project.id_project == StudentProject.id_project
            )
        )
    ).all()

    chosen: dict[tuple[int, int], tuple[str, int]] = {}
    for membership, project in rows:
        membership_code = membership.status.code
        if membership_code in (
            PendingApprovalMember.code,
            RejectedMember.code,
        ):
            continue
        project_code = project.status.code
        if membership_code in (Abandoned.code, Expelled.code):
            state = ABANDONED
        elif project_code == Approved.code:
            state = FINISHED_APPROVED
        elif project_code == Cancelled.code:
            state = FINISHED_FAILED
        elif membership_code == Finished.code:
            state = FINISHED_APPROVED
        else:
            state = ATTENDING

        key = (membership.id_student, project.id_section_year)
        current = chosen.get(key)
        if current is None or _CURSADA_PRIORITY[state] > _CURSADA_PRIORITY[current[0]]:
            chosen[key] = (state, project.section_year.year)

    attending_by_student: dict[int, int] = {}
    for (id_student, id_section_year), (state, year) in chosen.items():
        session.add(
            StudentSectionYear(
                id_student=id_student,
                id_section_year=id_section_year,
                year=year,
                state=state,
            )
        )
        if state == ATTENDING:
            previous = attending_by_student.get(id_student)
            if previous is not None and previous != id_section_year:
                raise ValueError(
                    "Seed: el alumno "
                    f"{id_student} tiene más de una cursada actual"
                )
            attending_by_student[id_student] = id_section_year
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
    await _load_student_section_years(session, data, students, section_years)
    calendars = {
        calendar.id_section_year: calendar
        for calendar in (
            await session.exec(
                select(Calendar).where(
                    Calendar.id_section_year.in_(
                        [sy.id_section_year for sy in section_years.values()]
                    )
                )
            )
        ).all()
    }
    await _load_calendar_classes(session, data, section_years, calendars)
    await _load_activities(session, data, section_years, calendars)
    projects = await _load_projects(session, data, section_years, statuses)
    await _load_student_projects(session, data, students, projects, statuses)
    await _load_student_cursadas(session)

    await session.commit()
