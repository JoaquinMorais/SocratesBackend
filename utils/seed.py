import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import (
    Activity,
    Attendance,
    AttendanceSession,
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
    Technology,
    ProjectTechnology,
    User,
)
from models.state import PROJECT_INITIAL
from models.state.state_project import Approved, Cancelled
from models.state.state_student_project import (
    Abandoned,
    Active,
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
from utils.security import hash_otp
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
            allow_project_joins=item.get("allow_project_joins", False),
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
    holidays = {
        date.fromisoformat(value) for value in data.get("calendar_holidays", [])
    }
    for item in data.get("calendar_class_series", []):
        key = (item["section"], item["year"])
        sy = section_years.get(key)
        if sy is None:
            raise _missing("el curso lectivo", key)
        calendar = calendars[sy.id_section_year]
        from_date = date.fromisoformat(item["from"])
        to_date = date.fromisoformat(item["to"])
        skipped = holidays | {
            date.fromisoformat(value) for value in item.get("skip_dates", [])
        }
        day = from_date
        while day <= to_date:
            if day.isoweekday() == item["weekday"] and day not in skipped:
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


_PROJECT_HISTORY = {
    "uninsured": ("uninsured",),
    "in_idea": ("uninsured", "in_idea"),
    "in_progress": ("uninsured", "in_idea", "in_progress"),
    "pending_approval": (
        "uninsured",
        "in_idea",
        "in_progress",
        "pending_approval",
    ),
    "rejected": (
        "uninsured",
        "in_idea",
        "in_progress",
        "pending_approval",
        "rejected",
    ),
    "approved": (
        "uninsured",
        "in_idea",
        "in_progress",
        "pending_approval",
        "approved",
    ),
    "cancelled": ("uninsured", "in_idea", "in_progress", "cancelled"),
}
_HISTORY_MONTH_DAY = {
    "uninsured": (3, 1),
    "in_idea": (3, 15),
    "in_progress": (5, 1),
    "pending_approval": (10, 1),
    "rejected": (10, 15),
    "approved": (11, 15),
    "cancelled": (9, 15),
}


def _history_datetime(year: int, index: int, code: str) -> datetime:
    if year == 2026 and code in ("pending_approval", "approved", "rejected"):
        month, day = {
            "pending_approval": (9, 20),
            "approved": (10, 15),
            "rejected": (9, 25),
        }[code]
    else:
        month, day = _HISTORY_MONTH_DAY.get(code, (3, 1))
    hour = 12 + min(index, 6)
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


async def _load_technologies(
    session: AsyncSession, data: dict
) -> dict[str, Technology]:
    technologies: dict[str, Technology] = {}
    for item in data.get("technologies", []):
        key = item["name"].strip().lower()
        if key in technologies:
            raise ValueError(f"Seed: tecnología repetida {item['name']!r}")
        technology = Technology(
            name=item["name"].strip(), description=item.get("description")
        )
        session.add(technology)
        technologies[key] = technology
    await session.flush()
    return technologies


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

        final_code = item.get("status", PROJECT_INITIAL)
        final_status = statuses.get(("project", final_code))
        if final_status is None:
            raise _missing("el estado", final_code)

        raw_history = item.get("status_history")
        if raw_history:
            history = [
                (entry["status"] if isinstance(entry, dict) else entry)
                for entry in raw_history
            ]
        else:
            history = list(_PROJECT_HISTORY.get(final_code, (final_code,)))
        if history[-1] != final_code:
            raise ValueError(
                f"Seed: el historial del proyecto {key} termina en "
                f"{history[-1]!r} y no en {final_code!r}"
            )

        project = Project(
            id_section_year=sy.id_section_year,
            group_number=item["group_number"],
            privacy=item["privacy"],
            status=final_status,
            name=item.get("name"),
            description=item.get("description"),
            objective=item.get("objective"),
            problem=item.get("problem"),
        )
        session.add(project)
        await session.flush()  # obtiene id_project

        previous: Status | None = None
        for index, code in enumerate(history):
            status = statuses.get(("project", code))
            if status is None:
                raise _missing("el estado", code)
            changed_at = None
            if raw_history and isinstance(raw_history[index], dict):
                value = raw_history[index].get("changed_at")
                if value:
                    changed_at = datetime.fromisoformat(value)
            session.add(
                ProjectStatus(
                    id_project=project.id_project,
                    id_status_from=previous.id_status if previous else None,
                    id_status_to=status.id_status,
                    changed_at=changed_at
                    or _history_datetime(sy.year, index, code),
                )
            )
            previous = status

        projects[(item["section"], item["year"], item["group_number"])] = project
    await session.flush()
    return projects


async def _load_project_technologies(
    session: AsyncSession,
    data: dict,
    projects: dict[tuple[str, int, int], Project],
    technologies: dict[str, Technology],
) -> None:
    seen: set[tuple[int, int]] = set()
    for item in data.get("project_technologies", []):
        key = (item["section"], item["year"], item["group_number"])
        project = projects.get(key)
        if project is None:
            raise _missing("el proyecto", key)
        technology = technologies.get(item["technology"].strip().lower())
        if technology is None:
            raise _missing("la tecnología", item["technology"])
        pair = (project.id_project, technology.id_technology)
        if pair in seen:
            raise ValueError(f"Seed: tecnología repetida en el proyecto {key}")
        seen.add(pair)
        session.add(
            ProjectTechnology(
                id_project=project.id_project,
                id_technology=technology.id_technology,
            )
        )
    await session.flush()


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
        if project_code == Cancelled.code and membership_code in (
            Active.code,
            Finished.code,
            Abandoned.code,
            Expelled.code,
        ):
            state = FINISHED_FAILED
        elif membership_code in (Abandoned.code, Expelled.code):
            state = ABANDONED
        elif project_code == Approved.code:
            state = FINISHED_APPROVED
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


async def _load_attendance(
    session: AsyncSession,
    data: dict,
    section_years: dict[tuple[str, int], SectionYear],
    calendars: dict[int, Calendar],
) -> None:
    """Genera asistencia determinista para una parte de las clases pasadas.

    La selección no usa azar: se eligen ~55% de las clases de cada curso y cada
    alumno tiene una tasa objetivo (la mayoría entre 60% y 100%). Así el seed es
    reproducible y sirve para probar listas, historiales y reportes.
    """
    config = data.get("attendance")
    if not config:
        return

    until = date.fromisoformat(config.get("until", "2026-10-30"))
    fraction = int(config.get("class_fraction", 55))
    high_rate = int(config.get("high_rate", 85))
    high_min = int(config.get("high_min", 60))
    high_max = int(config.get("high_max", 100))
    low_min = int(config.get("low_min", 35))
    low_max = int(config.get("low_max", 60))

    calendar_by_id = {
        calendar.id_calendar: calendar for calendar in calendars.values()
    }
    classes = (
        await session.exec(
            select(CalendarClass).where(CalendarClass.date <= until)
        )
    ).all()
    classes_by_section: dict[int, list[CalendarClass]] = {}
    for calendar_class in classes:
        calendar = calendar_by_id.get(calendar_class.id_calendar)
        if calendar is None:
            continue
        classes_by_section.setdefault(calendar.id_section_year, []).append(
            calendar_class
        )

    cursadas = (
        await session.exec(
            select(StudentSectionYear).where(
                StudentSectionYear.state.in_(
                    (ATTENDING, FINISHED_APPROVED, FINISHED_FAILED)
                )
            )
        )
    ).all()
    cursadas_by_section: dict[int, list[StudentSectionYear]] = {}
    for cursada in cursadas:
        cursadas_by_section.setdefault(cursada.id_section_year, []).append(cursada)

    for (section, year), sy in section_years.items():
        available = sorted(
            classes_by_section.get(sy.id_section_year, []),
            key=lambda item: (item.date, item.start_time, item.id_calendar_class),
        )
        if not available:
            continue
        selected = [
            item
            for index, item in enumerate(available)
            if ((index + 1) * 37 + sy.id_section_year * 13) % 100 < fraction
        ]
        if not selected:
            selected = [available[-1]]

        for calendar_class in selected:
            start = datetime.combine(
                calendar_class.date, calendar_class.start_time
            ).replace(tzinfo=timezone.utc)
            session.add(
                AttendanceSession(
                    id_calendar_class=calendar_class.id_calendar_class,
                    code_hash=hash_otp("000000"),
                    opened_at=start - timedelta(minutes=5),
                    expires_at=start + timedelta(minutes=10),
                    closed_at=start + timedelta(minutes=5),
                )
            )

        for cursada in cursadas_by_section.get(sy.id_section_year, []):
            bucket = (cursada.id_student * 17 + sy.id_section_year * 31) % 100
            if bucket < high_rate:
                rate = high_min + bucket % (high_max - high_min + 1)
            else:
                rate = low_min + bucket % (low_max - low_min + 1)
            target = math.ceil(rate * len(selected) / 100)
            ordered = sorted(
                selected,
                key=lambda item: (
                    (cursada.id_student * 31 + item.id_calendar_class * 17) % 1000,
                    item.date,
                    item.start_time,
                ),
            )
            for calendar_class in ordered[:target]:
                mix = (cursada.id_student * 13 + calendar_class.id_calendar_class) % 10
                method = "code" if mix <= 6 else "manual" if mix <= 8 else "transcript"
                start = datetime.combine(
                    calendar_class.date, calendar_class.start_time
                ).replace(tzinfo=timezone.utc)
                session.add(
                    Attendance(
                        id_student_section_year=cursada.id_student_section_year,
                        id_calendar_class=calendar_class.id_calendar_class,
                        method=method,
                        recorded_at=start + timedelta(minutes=1 + mix % 5),
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
    await _load_student_section_years(session, data, students, section_years)
    technologies = await _load_technologies(session, data)
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
    await _load_project_technologies(session, data, projects, technologies)
    await _load_student_projects(session, data, students, projects, statuses)
    await _load_student_cursadas(session)
    await _load_attendance(session, data, section_years, calendars)

    await session.commit()
