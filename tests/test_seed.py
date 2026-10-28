from sqlalchemy import text
from sqlmodel import SQLModel, func, select

from config.database import SessionLocal
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
from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN
from utils.seed import DATA_DIR, load_seed

FULL_SEED = DATA_DIR / "seed.json"


async def _load_full_seed() -> None:
    """Vacía la BD (que ya trae el seed de tests) y carga el seed real."""
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    async with SessionLocal() as session:
        connection = await session.connection()
        await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        await load_seed(session, seed_path=FULL_SEED)


async def _count(model) -> int:
    async with SessionLocal() as session:
        return (await session.exec(select(func.count()).select_from(model))).one()


async def test_seed_loads_expected_counts():
    await _load_full_seed()
    assert await _count(Section) == 4
    assert await _count(SectionYear) == 7
    assert await _count(Professor) == 10
    assert await _count(Student) == 25
    assert await _count(ProfessorSectionYear) == 21
    assert await _count(Project) == 14
    assert await _count(StudentProject) == 22
    assert await _count(StudentSectionYear) == 32
    assert await _count(Calendar) == 7
    assert await _count(CalendarClass) == 548
    assert await _count(Activity) == 14


async def test_seed_group_size_ranges():
    await _load_full_seed()
    async with SessionLocal() as session:
        section_years = (await session.exec(select(SectionYear))).all()
    assert len(section_years) == 7
    for sy in section_years:
        if sy.year == 2025:
            assert (sy.min_students, sy.max_students) == (3, 10)
        else:
            assert (sy.min_students, sy.max_students) == (5, 10)


async def test_seed_three_distinct_professors_per_section_year():
    await _load_full_seed()
    async with SessionLocal() as session:
        section_years = (await session.exec(select(SectionYear))).all()
        assignments = (await session.exec(select(ProfessorSectionYear))).all()
    for sy in section_years:
        ids = [a.id_professor for a in assignments if a.id_section_year == sy.id_section_year]
        assert len(ids) == 3, f"{sy.year} {sy.id_section} no tiene 3 profesores"
        assert len(set(ids)) == 3, "hay un profesor repetido en el mismo curso lectivo"


async def test_seed_two_groups_per_section_year():
    await _load_full_seed()
    async with SessionLocal() as session:
        section_years = (await session.exec(select(SectionYear))).all()
        projects = (await session.exec(select(Project))).all()
    for sy in section_years:
        groups = sorted(p.group_number for p in projects if p.id_section_year == sy.id_section_year)
        assert groups == [1, 2], f"{sy.year} {sy.id_section} no tiene los grupos 1 y 2"


async def test_seed_privacy_values_are_valid():
    await _load_full_seed()
    async with SessionLocal() as session:
        projects = (await session.exec(select(Project))).all()
    assert {p.privacy for p in projects} <= {"public", "private", "protected"}


async def test_seed_statuses_are_loaded():
    await _load_full_seed()
    async with SessionLocal() as session:
        statuses = (await session.exec(select(Status))).all()
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
    }
    final = {s.code for s in statuses if s.is_final}
    assert final == {"approved", "cancelled", "abandoned", "finished", "expelled"}


async def test_seed_each_project_with_members_has_exactly_one_leader():
    await _load_full_seed()
    async with SessionLocal() as session:
        memberships = (await session.exec(select(StudentProject))).all()
    leaders: dict[int, int] = {}
    for m in memberships:
        if m.is_leader:
            leaders[m.id_project] = leaders.get(m.id_project, 0) + 1
    assert all(count == 1 for count in leaders.values())
    assert set(leaders) == {m.id_project for m in memberships}


async def test_seed_membership_status_follows_leader_rule():
    await _load_full_seed()
    async with SessionLocal() as session:
        memberships = (await session.exec(select(StudentProject))).all()
    for m in memberships:
        expected = "active" if m.is_leader else "pending_approval"
        assert m.status.code == expected


async def test_seed_projects_and_memberships_have_status_of_their_ambito():
    await _load_full_seed()
    async with SessionLocal() as session:
        projects = (await session.exec(select(Project))).all()
        memberships = (await session.exec(select(StudentProject))).all()
    assert all(p.status.ambito == "project" for p in projects)
    assert all(m.status.ambito == "student_project" for m in memberships)


async def test_seed_every_project_has_initial_status_history():
    await _load_full_seed()
    async with SessionLocal() as session:
        projects = (await session.exec(select(Project))).all()
        histories = (await session.exec(select(ProjectStatus))).all()
    by_project: dict[int, list[ProjectStatus]] = {}
    for h in histories:
        by_project.setdefault(h.id_project, []).append(h)
    assert set(by_project) == {p.id_project for p in projects}
    for pid, records in by_project.items():
        ordered = sorted(records, key=lambda r: r.id_project_status)
        assert ordered[0].id_status_from is None, f"proyecto {pid}: el primer registro debe tener status_from null"
        assert len(records) >= 1


async def test_seed_emails_and_legajos_are_unique():
    await _load_full_seed()
    async with SessionLocal() as session:
        professors = (await session.exec(select(Professor))).all()
        students = (await session.exec(select(Student))).all()
        legajos = (await session.exec(select(Student.id_student))).all()
    mails = [p.mail for p in professors]
    assert len(mails) == len(set(mails))
    professor_legajos = [p.user.legajo for p in professors]
    assert len(professor_legajos) == len(set(professor_legajos))
    student_legajos = [s.user.legajo for s in students]
    assert len(student_legajos) == len(set(student_legajos))
    assert len(legajos) == len(set(legajos))


async def test_seed_users_are_adults():
    await _load_full_seed()
    async with SessionLocal() as session:
        users = (await session.exec(select(User))).all()
    assert all(u.age >= 18 for u in users)


async def test_seed_students_have_at_most_one_member_group():
    await _load_full_seed()
    async with SessionLocal() as session:
        memberships = (await session.exec(select(StudentProject))).all()
    by_student: dict[int, int] = {}
    for m in memberships:
        if m.status.code in ("active", "finished"):
            by_student[m.id_student] = by_student.get(m.id_student, 0) + 1
    assert all(count == 1 for count in by_student.values())
    assert by_student  # hay al menos un miembro


async def test_seed_all_projects_belong_to_a_section_year():
    await _load_full_seed()
    async with SessionLocal() as session:
        projects = (await session.exec(select(Project))).all()
        ids = set((await session.exec(select(SectionYear.id_section_year))).all())
    assert all(p.id_section_year in ids for p in projects)


async def test_seed_users_can_log_in(client, login):
    await _load_full_seed()
    await login(STUDENT, PASSWORD)
    await login(SUPER_ADMIN, PASSWORD)
    r = await client.post(
        "/auth/login",
        json={"email": "carlos.ruiz@frc.utn.edu.ar", "password": PASSWORD},
    )
    assert r.status_code == 200


async def test_seed_student_section_years_are_consistent():
    await _load_full_seed()
    async with SessionLocal() as session:
        rows = (await session.exec(select(StudentSectionYear))).all()
        pairs = [(r.id_student, r.id_section_year) for r in rows]
        assert len(pairs) == len(set(pairs)), "hay cursadas repetidas"
        per_year = [(r.id_student, r.year) for r in rows]
        assert len(per_year) == len(set(per_year)), "hay un alumno con dos cursadas del mismo año"

        student_ids = set((await session.exec(select(Student.id_student))).all())
        section_year_ids = set(
            (await session.exec(select(SectionYear.id_section_year))).all()
        )
        assert all(
            s in student_ids and sy in section_year_ids for s, sy in pairs
        ), "alguna cursada apunta a un alumno o curso lectivo inexistente"

        # todo alumno con grupo está inscripto en el curso lectivo de ese proyecto
        memberships = (
            await session.exec(
                select(StudentProject.id_student, Project.id_section_year).join(
                    Project, Project.id_project == StudentProject.id_project
                )
            )
        ).all()
        assert all((s, sy) in set(pairs) for s, sy in memberships)


async def test_seed_students_may_have_several_section_years():
    await _load_full_seed()
    async with SessionLocal() as session:
        rows = (await session.exec(select(StudentSectionYear))).all()
        counts: dict[int, int] = {}
        for row in rows:
            counts[row.id_student] = counts.get(row.id_student, 0) + 1
        assert any(count >= 2 for count in counts.values())


async def test_seed_calendars_are_consistent():
    await _load_full_seed()
    async with SessionLocal() as session:
        section_years = (await session.exec(select(SectionYear))).all()
        calendars = (await session.exec(select(Calendar))).all()
        # un calendario por curso lectivo (1 a 1)
        assert len(calendars) == len(section_years)
        assert {c.id_section_year for c in calendars} == {
            sy.id_section_year for sy in section_years
        }

        classes = (await session.exec(select(CalendarClass))).all()
        year_by_section_year = {sy.id_section_year: sy.year for sy in section_years}
        calendar_by_id = {c.id_calendar: c for c in calendars}
        assert all(
            row.date.year
            == year_by_section_year[calendar_by_id[row.id_calendar].id_section_year]
            for row in classes
        ), "hay clases fuera del año del curso lectivo"
        assert all(
            row.end_time > row.start_time for row in classes
        ), "fin no posterior al inicio"
        assert all(
            row.modality in {"in_person", "virtual"} for row in classes
        ), "modalidad inválida"

        # sin solapamientos dentro del mismo calendario y día
        by_day: dict[tuple[int, object], list[CalendarClass]] = {}
        for row in classes:
            by_day.setdefault((row.id_calendar, row.date), []).append(row)
        for slots in by_day.values():
            slots.sort(key=lambda r: r.start_time)
            for previous, current in zip(slots, slots[1:]):
                assert previous.end_time <= current.start_time, "hay clases superpuestas"

        # cada calendario/cursos lectivo del seed tiene clases
        assert all(
            any(row.id_calendar == c.id_calendar for row in classes)
            for c in calendars
        )


async def test_seed_activities_are_consistent():
    await _load_full_seed()
    async with SessionLocal() as session:
        activities = (await session.exec(select(Activity))).all()
        calendars = (await session.exec(select(Calendar))).all()
        section_years = (await session.exec(select(SectionYear))).all()
        year_by_section_year = {sy.id_section_year: sy.year for sy in section_years}
        calendar_by_id = {c.id_calendar: c for c in calendars}
        assert all(
            activity.due_date.year
            == year_by_section_year[calendar_by_id[activity.id_calendar].id_section_year]
            for activity in activities
        ), "hay actividades fuera del año del curso lectivo"
        assert all(activity.title.strip() for activity in activities)
        assert all(
            activity.id_calendar in calendar_by_id for activity in activities
        )
        # cada curso lectivo del seed tiene actividades
        assert {activity.id_calendar for activity in activities} == set(
            calendar_by_id
        )
