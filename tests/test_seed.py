from collections import Counter, defaultdict
from datetime import date

import pytest_asyncio
from sqlalchemy import text
from sqlmodel import SQLModel, func, select

from config.database import SessionLocal
from models import (
    Activity,
    Attendance,
    AttendanceSession,
    Calendar,
    CalendarClass,
    Delivery,
    Professor,
    ProfessorSectionYear,
    Project,
    ProjectStatus,
    ProjectTechnology,
    Section,
    SectionYear,
    Status,
    Student,
    StudentProject,
    StudentSectionYear,
    Technology,
    User,
)
from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN
from utils.seed import DATA_DIR, load_seed

FULL_SEED = DATA_DIR / "seed.json"
TEST_SEED = DATA_DIR / "seed_test.json"


async def _load_seed(path):
    """Vacía la BD y carga el seed indicado."""
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    async with SessionLocal() as session:
        connection = await session.connection()
        await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        await load_seed(session, seed_path=path)


@pytest_asyncio.fixture(scope="module", loop_scope="session", autouse=True)
async def full_seed(database):
    """Carga el seed real una sola vez por módulo y restaura el seed de tests."""
    await _load_seed(FULL_SEED)
    yield
    await _load_seed(TEST_SEED)


async def _count(model) -> int:
    async with SessionLocal() as session:
        return (await session.exec(select(func.count()).select_from(model))).one()


async def _all(model):
    async with SessionLocal() as session:
        return (await session.exec(select(model))).all()


async def test_seed_key_counts():
    assert await _count(Section) == 4
    assert await _count(SectionYear) == 10
    assert await _count(Professor) == 16
    assert await _count(Student) == 200
    assert await _count(ProfessorSectionYear) == 30
    assert await _count(Project) == 32
    assert await _count(Calendar) == 10
    assert await _count(Activity) == 30
    assert await _count(Technology) == 20
    assert await _count(ProjectTechnology) == 95


async def test_seed_section_years_allow_project_joins():
    section_years = await _all(SectionYear)
    assert len(section_years) == 10
    enabled = {(sy.section.name, sy.year) for sy in section_years if sy.allow_project_joins}
    assert enabled == {("3K2", 2025), ("3K3", 2026)}


async def test_seed_group_size_ranges_and_years():
    section_years = await _all(SectionYear)
    assert {sy.section.name for sy in section_years} == {"3K1", "3K2", "3K3", "3K4"}
    by_key = {(sy.section.name, sy.year) for sy in section_years}
    assert {(f"3K{i}", 2024) for i in range(1, 5)} <= by_key
    assert not any(section == "3K4" and year != 2024 for section, year in by_key)
    assert all((sy.min_students, sy.max_students) == (5, 10) for sy in section_years)

    memberships = await _all(StudentProject)
    sizes = Counter(m.id_project for m in memberships)
    assert sizes
    assert all(5 <= size <= 10 for size in sizes.values()), sizes


async def test_seed_three_distinct_professors_per_section_year():
    section_years = await _all(SectionYear)
    assignments = await _all(ProfessorSectionYear)
    for sy in section_years:
        ids = [a.id_professor for a in assignments if a.id_section_year == sy.id_section_year]
        assert len(ids) == 3, f"{sy.year} {sy.section.name} no tiene 3 profesores"
        assert len(set(ids)) == 3, "hay un profesor repetido en el mismo curso lectivo"


async def test_seed_projects_have_unique_group_numbers_per_section_year():
    projects = await _all(Project)
    by_section_year = defaultdict(list)
    for project in projects:
        by_section_year[project.id_section_year].append(project.group_number)
    for section_year_id, groups in by_section_year.items():
        assert groups == list(range(1, len(groups) + 1)), section_year_id
        assert 2 <= len(groups) <= 4


async def test_seed_projects_cover_all_states():
    projects = await _all(Project)
    assert {p.status.code for p in projects} == {
        "uninsured",
        "in_idea",
        "in_progress",
        "pending_approval",
        "rejected",
        "approved",
        "cancelled",
    }


async def test_seed_memberships_cover_all_states():
    memberships = await _all(StudentProject)
    assert {m.status.code for m in memberships} == {
        "active",
        "pending_approval",
        "abandoned",
        "finished",
        "expelled",
        "rejected",
    }


async def test_seed_privacy_values_are_valid():
    projects = await _all(Project)
    assert {p.privacy for p in projects} <= {"public", "private", "protected"}


async def test_seed_statuses_are_loaded():
    statuses = await _all(Status)
    pairs = {(s.ambito, s.code) for s in statuses}
    assert pairs == {
        ("project", "uninsured"),
        ("project", "in_idea"),
        ("project", "in_progress"),
        ("project", "pending_approval"),
        ("project", "rejected"),
        ("project", "approved"),
        ("project", "cancelled"),
        ("student_project", "active"),
        ("student_project", "pending_approval"),
        ("student_project", "abandoned"),
        ("student_project", "finished"),
        ("student_project", "expelled"),
        ("student_project", "rejected"),
        ("student_section_year", "registered"),
        ("student_section_year", "attending"),
        ("student_section_year", "abandoned"),
        ("student_section_year", "finished_approved"),
        ("student_section_year", "finished_failed"),
        ("delivery", "requested"),
        ("delivery", "pending_approval"),
        ("delivery", "pending_modification"),
        ("delivery", "approved"),
    }
    final = {(s.ambito, s.code) for s in statuses if s.is_final}
    assert final == {
        ("project", "approved"),
        ("project", "cancelled"),
        ("student_project", "abandoned"),
        ("student_project", "finished"),
        ("student_project", "expelled"),
        ("student_section_year", "registered"),
        ("student_section_year", "finished_approved"),
        ("delivery", "approved"),
    }


async def test_seed_each_project_with_members_has_exactly_one_leader():
    memberships = await _all(StudentProject)
    leaders = Counter(m.id_project for m in memberships if m.is_leader)
    assert leaders
    assert all(count == 1 for count in leaders.values())
    assert set(leaders) == {m.id_project for m in memberships}


async def test_seed_membership_statuses_are_valid_and_consistent():
    memberships = await _all(StudentProject)
    for membership in memberships:
        assert membership.status.ambito == "student_project"
        if membership.is_leader:
            assert membership.status.code in {
                "active",
                "finished",
                "abandoned",
            }, membership.status.code


async def test_seed_cancelled_projects_have_failed_cursadas():
    projects = await _all(Project)
    cancelled = {p.id_project for p in projects if p.status.code == "cancelled"}
    memberships = await _all(StudentProject)
    cursadas = await _all(StudentSectionYear)
    failed = {
        (c.id_student, c.id_section_year)
        for c in cursadas
        if c.state == "finished_failed"
    }
    for membership in memberships:
        if membership.id_project in cancelled:
            project = next(p for p in projects if p.id_project == membership.id_project)
            assert membership.status.code in {"abandoned", "rejected"}
            if membership.status.code != "rejected":
                assert (membership.id_student, project.id_section_year) in failed


async def test_seed_projects_and_memberships_have_status_of_their_ambito():
    projects = await _all(Project)
    memberships = await _all(StudentProject)
    assert all(p.status.ambito == "project" for p in projects)
    assert all(m.status.ambito == "student_project" for m in memberships)


async def test_seed_project_status_history_matches_current_status():
    projects = await _all(Project)
    histories = await _all(ProjectStatus)
    by_project = defaultdict(list)
    for history in histories:
        by_project[history.id_project].append(history)
    assert set(by_project) == {p.id_project for p in projects}
    for project in projects:
        ordered = sorted(by_project[project.id_project], key=lambda r: r.id_project_status)
        assert ordered[0].id_status_from is None
        assert ordered[-1].id_status_to == project.id_status
        assert len(ordered) >= 1


async def test_seed_emails_and_legajos_are_unique():
    professors = await _all(Professor)
    students = await _all(Student)
    mails = [p.mail for p in professors]
    assert len(mails) == len(set(mails))
    professor_legajos = [p.user.legajo for p in professors]
    assert len(professor_legajos) == len(set(professor_legajos))
    student_legajos = [s.user.legajo for s in students]
    assert len(student_legajos) == len(set(student_legajos))


async def test_seed_users_are_adults():
    users = await _all(User)
    assert all(user.age >= 18 for user in users)


async def test_seed_students_have_at_most_one_member_group():
    memberships = await _all(StudentProject)
    by_student = Counter(
        m.id_student for m in memberships if m.status.code in ("active", "finished")
    )
    assert by_student
    assert all(count == 1 for count in by_student.values())


async def test_seed_all_projects_belong_to_a_section_year():
    projects = await _all(Project)
    section_year_ids = {sy.id_section_year for sy in await _all(SectionYear)}
    assert all(p.id_section_year in section_year_ids for p in projects)


async def test_seed_users_can_log_in(client, login):
    await login(STUDENT, PASSWORD)
    await login(SUPER_ADMIN, PASSWORD)
    response = await client.post(
        "/auth/login",
        json={"email": "carlos.ruiz@frc.utn.edu.ar", "password": PASSWORD},
    )
    assert response.status_code == 200


async def test_seed_student_section_years_are_consistent():
    rows = await _all(StudentSectionYear)

    registrations = [r for r in rows if r.state == "registered"]
    registrations_per_year = [(r.id_student, r.year) for r in registrations]
    assert len(registrations_per_year) == len(set(registrations_per_year))

    cursadas = [r for r in rows if r.state != "registered"]
    cursadas_per_section = [(r.id_student, r.id_section_year) for r in cursadas]
    assert len(cursadas_per_section) == len(set(cursadas_per_section))

    attending = [r for r in rows if r.state == "attending"]
    assert len({r.id_student for r in attending}) == len(attending)
    assert {r.state for r in rows} == {
        "registered",
        "attending",
        "abandoned",
        "finished_approved",
        "finished_failed",
    }

    student_ids = {s.id_student for s in await _all(Student)}
    section_year_ids = {sy.id_section_year for sy in await _all(SectionYear)}
    assert all(
        r.id_student in student_ids and r.id_section_year in section_year_ids
        for r in rows
    )

    async with SessionLocal() as session:
        memberships = (
            await session.exec(
                select(StudentProject.id_student, Project.id_section_year)
                .join(Project, Project.id_project == StudentProject.id_project)
                .join(Status, Status.id_status == StudentProject.id_status)
                .where(Status.code.notin_(("pending_approval", "rejected")))
            )
        ).all()
    pairs = {(r.id_student, r.id_section_year) for r in cursadas}
    assert all((student, section_year) in pairs for student, section_year in memberships)


async def test_seed_students_may_have_several_section_years():
    rows = await _all(StudentSectionYear)
    counts = Counter(row.id_student for row in rows)
    assert any(count >= 2 for count in counts.values())


async def test_seed_calendars_are_consistent():
    section_years = await _all(SectionYear)
    calendars = await _all(Calendar)
    assert len(calendars) == len(section_years)
    assert {c.id_section_year for c in calendars} == {
        sy.id_section_year for sy in section_years
    }

    classes = await _all(CalendarClass)
    year_by_section_year = {sy.id_section_year: sy.year for sy in section_years}
    calendar_by_id = {c.id_calendar: c for c in calendars}
    assert all(
        row.date.year
        == year_by_section_year[calendar_by_id[row.id_calendar].id_section_year]
        for row in classes
    )
    assert all(row.end_time > row.start_time for row in classes)
    assert all(row.modality in {"in_person", "virtual"} for row in classes)

    by_day = defaultdict(list)
    for row in classes:
        by_day[(row.id_calendar, row.date)].append(row)
    for slots in by_day.values():
        slots.sort(key=lambda row: row.start_time)
        for previous, current in zip(slots, slots[1:]):
            assert previous.end_time <= current.start_time

    assert all(
        any(row.id_calendar == calendar.id_calendar for row in classes)
        for calendar in calendars
    )


async def test_seed_activities_are_consistent():
    activities = await _all(Activity)
    calendars = await _all(Calendar)
    section_years = await _all(SectionYear)
    year_by_section_year = {sy.id_section_year: sy.year for sy in section_years}
    calendar_by_id = {c.id_calendar: c for c in calendars}
    assert all(
        activity.due_date.year
        == year_by_section_year[calendar_by_id[activity.id_calendar].id_section_year]
        for activity in activities
    )
    assert all(activity.title.strip() for activity in activities)
    assert all(activity.id_calendar in calendar_by_id for activity in activities)
    assert {activity.id_calendar for activity in activities} == set(calendar_by_id)
    assert all(isinstance(activity.link_required, bool) for activity in activities)
    assert any(activity.link_required for activity in activities)
    assert any(not activity.link_required for activity in activities)


async def test_seed_deliveries_are_precreated():
    projects = await _all(Project)
    activities = await _all(Activity)
    deliveries = await _all(Delivery)
    section_years = await _all(SectionYear)
    calendars = await _all(Calendar)

    calendar_by_section = {
        calendar.id_section_year: calendar.id_calendar for calendar in calendars
    }
    activities_by_section = Counter()
    for activity in activities:
        calendar_id = activity.id_calendar
        section_year_id = next(
            key for key, value in calendar_by_section.items() if value == calendar_id
        )
        activities_by_section[section_year_id] += 1

    expected = sum(
        activities_by_section[project.id_section_year] for project in projects
    )
    assert len(deliveries) == expected
    pairs = {(delivery.id_project, delivery.id_activity) for delivery in deliveries}
    assert len(pairs) == len(deliveries)
    assert any(delivery.link is not None for delivery in deliveries)
    assert any(delivery.link is None for delivery in deliveries)
    assert any(delivery.activity_grade is not None for delivery in deliveries)
    assert {delivery.status.code for delivery in deliveries} == {
        "requested",
        "pending_approval",
        "pending_modification",
        "approved",
    }
    section_year_ids = {sy.id_section_year for sy in section_years}
    assert all(project.id_section_year in section_year_ids for project in projects)


async def test_seed_technology_catalog_and_links():
    technologies = await _all(Technology)
    names = [technology.name.casefold() for technology in technologies]
    assert len(names) == len(set(names))
    projects = await _all(Project)
    project_ids = {p.id_project for p in projects}
    technology_ids = {t.id_technology for t in technologies}
    links = await _all(ProjectTechnology)
    seen = set()
    for link in links:
        pair = (link.id_project, link.id_technology)
        assert pair not in seen
        seen.add(pair)
        assert link.id_project in project_ids
        assert link.id_technology in technology_ids
    assert links


async def test_seed_attendance_is_consistent():
    attendance = await _all(Attendance)
    sessions = await _all(AttendanceSession)
    classes = await _all(CalendarClass)
    calendars = await _all(Calendar)
    cursadas = await _all(StudentSectionYear)

    class_by_id = {c.id_calendar_class: c for c in classes}
    calendar_by_id = {c.id_calendar: c for c in calendars}
    cursada_by_id = {c.id_student_section_year: c for c in cursadas}

    assert attendance
    assert sessions
    pairs = set()
    for row in attendance:
        pair = (row.id_student_section_year, row.id_calendar_class)
        assert pair not in pairs
        pairs.add(pair)
        assert row.method in {"code", "manual", "transcript"}
        cursada = cursada_by_id[row.id_student_section_year]
        assert cursada.state in {"attending", "finished_approved", "finished_failed"}
        calendar_class = class_by_id[row.id_calendar_class]
        assert calendar_class.date <= date(2026, 10, 30)
        assert calendar_by_id[calendar_class.id_calendar].id_section_year == cursada.id_section_year

    session_classes = {s.id_calendar_class for s in sessions}
    assert all(s.closed_at is not None for s in sessions)
    assert all(s.expires_at > s.opened_at for s in sessions)
    assert session_classes
    assert {a.id_calendar_class for a in attendance} <= session_classes

    # ~50/60% de las clases tienen toma.
    classes_by_section = defaultdict(list)
    for calendar_class in classes:
        if calendar_class.date <= date(2026, 10, 30):
            section_year_id = calendar_by_id[calendar_class.id_calendar].id_section_year
            classes_by_section[section_year_id].append(calendar_class.id_calendar_class)
    for section_year_id, class_ids in classes_by_section.items():
        selected = sum(1 for class_id in class_ids if class_id in session_classes)
        assert 0.45 <= selected / len(class_ids) <= 0.65

    # La mayoría de los alumnos tiene entre 60% y 100% de asistencia sobre las
    # clases que tuvieron toma.
    attendance_count = Counter(a.id_student_section_year for a in attendance)
    rates = []
    for cursada in cursadas:
        if cursada.state not in {"attending", "finished_approved", "finished_failed"}:
            continue
        total = len(classes_by_section.get(cursada.id_section_year, []))
        if total:
            selected = sum(
                1
                for class_id in classes_by_section[cursada.id_section_year]
                if class_id in session_classes
            )
            if selected:
                rates.append(attendance_count[cursada.id_student_section_year] / selected)
    assert rates
    assert sum(1 for rate in rates if rate >= 0.60) / len(rates) >= 0.80
