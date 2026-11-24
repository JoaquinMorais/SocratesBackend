from datetime import date, time, timedelta

import pytest_asyncio
from sqlalchemy import text
from sqlmodel import SQLModel, func, select

from config.database import SessionLocal
from models import (
    Activity,
    Calendar,
    CalendarClass,
    Delivery,
    DeliveryGrade,
    Professor,
    ProfessorSectionYear,
    Project,
    Section,
    SectionYear,
    Student,
    StudentProject,
    StudentSectionYear,
    User,
)
from utils.seed import DATA_DIR, load_seed

REAL_SEED = DATA_DIR / "seed_real.json"
TEST_SEED = DATA_DIR / "seed_test.json"
PASSWORD = "Pass1234"


async def _load_seed(path):
    """Vacía la BD y carga el seed indicado."""
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    async with SessionLocal() as session:
        connection = await session.connection()
        await connection.execute(
            text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE")
        )
        await load_seed(session, seed_path=path)


@pytest_asyncio.fixture(scope="module", loop_scope="session", autouse=True)
async def real_seed(database):
    """Carga la seed real una sola vez por módulo y restaura la de tests."""
    await _load_seed(REAL_SEED)
    yield
    await _load_seed(TEST_SEED)


async def _count(model) -> int:
    async with SessionLocal() as session:
        return (await session.exec(select(func.count()).select_from(model))).one()


async def _all(model):
    async with SessionLocal() as session:
        return (await session.exec(select(model))).all()


async def _legajo_by_student() -> dict[int, int]:
    async with SessionLocal() as session:
        rows = (
            await session.exec(
                select(Student, User).join(User, User.id_user == Student.id_student)
            )
        ).all()
    return {student.id_student: user.legajo for student, user in rows}


async def test_seed_real_key_counts():
    assert await _count(Section) == 3
    assert await _count(SectionYear) == 3
    assert await _count(Student) == 97
    assert await _count(Professor) == 4
    assert await _count(Project) == 18
    assert await _count(StudentProject) == 97
    assert await _count(StudentSectionYear) == 194
    assert await _count(ProfessorSectionYear) == 3


async def test_seed_real_professors():
    async with SessionLocal() as session:
        professors = (await session.exec(select(Professor))).all()
        users = {
            professor.id_professor: await session.get(User, professor.id_professor)
            for professor in professors
        }

    expected = {
        "marta.rodriguez@frc.utn.edu.ar": ("Marta", "Rodríguez", 200001, True),
        "dherrera68@gmail.com": ("Daniel", "Herrera", 200002, False),
        "ceciliaortiz76@gmail.com": ("María Cecilia", "Ortiz", 200003, True),
        "ritamperezmacchi@gmail.com": ("Rita", "Pérez", 200004, False),
    }
    assert {professor.mail for professor in professors} == set(expected)
    for professor in professors:
        first_name, last_name, legajo, is_super_admin = expected[professor.mail]
        user = users[professor.id_professor]
        assert professor.is_super_admin is is_super_admin
        assert user.first_name == first_name
        assert user.last_name == last_name
        assert user.legajo == legajo
        assert date(1970, 1, 1) <= user.birth_date <= date(1990, 12, 31)
        assert user.verify_password(PASSWORD)


async def test_seed_real_professors_assigned_to_3k1():
    async with SessionLocal() as session:
        section_year = (
            await session.exec(
                select(SectionYear)
                .join(Section, Section.id_section == SectionYear.id_section)
                .where(Section.name == "3K1", SectionYear.year == 2026)
            )
        ).one()
        assignments = (
            await session.exec(
                select(ProfessorSectionYear).where(
                    ProfessorSectionYear.id_section_year
                    == section_year.id_section_year
                )
            )
        ).all()
        professors = {
            professor.id_professor: professor
            for professor in (await session.exec(select(Professor))).all()
        }

    mails = {professors[assignment.id_professor].mail for assignment in assignments}
    assert mails == {
        "dherrera68@gmail.com",
        "ceciliaortiz76@gmail.com",
        "ritamperezmacchi@gmail.com",
    }
    assert "marta.rodriguez@frc.utn.edu.ar" not in mails


async def test_seed_real_students_normalized_and_without_duplicates():
    students = await _all(Student)
    users = await _all(User)
    student_ids = {student.id_student for student in students}

    assert len({user.legajo for user in users if user.id_user in student_ids}) == 97
    assert all(student.enrollment_year == 2024 for student in students)
    assert all(
        date(2000, 1, 1) <= user.birth_date <= date(2005, 12, 31)
        for user in users
        if user.id_user in student_ids
    )
    assert all(user.first_name and user.last_name for user in users)
    assert all(
        user.first_name == user.first_name.strip()
        and user.last_name == user.last_name.strip()
        for user in users
    )


async def test_seed_real_projects_in_progress_and_public():
    projects = await _all(Project)
    assert len(projects) == 18
    assert all(project.status.code == "in_progress" for project in projects)
    assert all(project.privacy == "public" for project in projects)
    assert all(project.name for project in projects)
    assert sorted(project.group_number for project in projects) == list(range(1, 19))


async def test_seed_real_project_names_and_descriptions():
    expected = {
        1: ("SIGPROMIN", "Gestión de Activos Mineros"),
        2: ("Asistencia en Violencia de Género", None),
        3: ("GOP", "Gestor de Obras de Pintura"),
        4: ("Gestión Integral de Taller Automotriz", None),
        5: ("Socrates", "Gestión de Proyectos Académicos"),
        6: ("Gestión de Mantenimiento de Vehículos", None),
        7: ("SmartPick Diesel", "Gestión de Pedidos y Optimización Logística"),
        8: ("ViajeZazo", "Planificador de Itinerario de Viaje"),
        9: ("Gestor de Actividades y Recursos del Polideportivo", None),
        10: ("Gestión de la Flota de Automóviles", None),
        11: ("AbogacIA", "Gestión Judicial Inteligente"),
        12: ("EnFOCO", "Gestión de Producciones Audiovisuales"),
        13: ("iterBus", "Gestión de Agenda de Flota de Colectivos"),
        14: ("ATLAS", "Gestor de Comunicación Formal"),
        15: ("Gestión de Clínica Dental", None),
        16: ("RentART", "Gestión de Alquileres de Inmuebles"),
        17: ("Gestión y Auditoría de Inventario", None),
        18: ("Hiperfoco", "Gestión Hiperfoco"),
    }
    projects = {project.group_number: project for project in await _all(Project)}
    assert set(projects) == set(expected)
    for group_number, (name, description) in expected.items():
        project = projects[group_number]
        assert project.name == name
        assert project.description == description


async def test_seed_real_one_leader_per_group():
    memberships = await _all(StudentProject)
    leaders = [membership for membership in memberships if membership.is_leader]
    assert len(leaders) == 18
    assert len({leader.id_project for leader in leaders}) == 18
    assert all(membership.status.code == "active" for membership in memberships)


async def test_seed_real_group_18_has_only_leonardo():
    legajos = await _legajo_by_student()
    projects = await _all(Project)
    memberships = await _all(StudentProject)
    project_by_number = {project.group_number: project for project in projects}

    group_18 = [
        membership
        for membership in memberships
        if membership.id_project == project_by_number[18].id_project
    ]
    assert len(group_18) == 1
    assert legajos[group_18[0].id_student] == 29886

    group_10 = [
        membership
        for membership in memberships
        if membership.id_project == project_by_number[10].id_project
    ]
    assert len(group_10) == 4
    assert all(legajos[membership.id_student] != 29886 for membership in group_10)


async def test_seed_real_3k4_students_registered_there_and_attending_3k1():
    expected_legajos = {402586, 78737, 99261, 77135, 90496}
    legajos = await _legajo_by_student()
    section_years = await _all(SectionYear)
    by_key = {
        (section_year.section.name, section_year.year): section_year
        for section_year in section_years
    }
    rows = await _all(StudentSectionYear)

    registered_3k4 = {
        legajos[row.id_student]
        for row in rows
        if row.id_section_year == by_key[("3K4", 2026)].id_section_year
        and row.state == "registered"
    }
    assert registered_3k4 == expected_legajos

    for legajo in expected_legajos:
        attending_3k1 = [
            row
            for row in rows
            if legajos[row.id_student] == legajo
            and row.id_section_year == by_key[("3K1", 2026)].id_section_year
            and row.state == "attending"
        ]
        assert len(attending_3k1) == 1


async def test_seed_real_calendar_classes():
    async with SessionLocal() as session:
        section_year = (
            await session.exec(
                select(SectionYear)
                .join(Section, Section.id_section == SectionYear.id_section)
                .where(Section.name == "3K1", SectionYear.year == 2026)
            )
        ).one()
        calendar = (
            await session.exec(
                select(Calendar).where(
                    Calendar.id_section_year == section_year.id_section_year
                )
            )
        ).one()
        classes = (
            await session.exec(
                select(CalendarClass)
                .where(CalendarClass.id_calendar == calendar.id_calendar)
                .order_by(CalendarClass.date)
            )
        ).all()

    assert len(classes) == 33
    assert {calendar_class.date.isoweekday() for calendar_class in classes} == {2, 3}
    assert all(
        date(2026, 8, 1) <= calendar_class.date <= date(2026, 11, 28)
        for calendar_class in classes
    )

    tuesdays = [c for c in classes if c.date.isoweekday() == 2]
    wednesdays = [c for c in classes if c.date.isoweekday() == 3]
    assert len(tuesdays) == 17
    assert len(wednesdays) == 16
    assert tuesdays[0].date == date(2026, 8, 4)
    assert tuesdays[-1].date == date(2026, 11, 24)
    assert wednesdays[0].date == date(2026, 8, 5)
    assert wednesdays[-1].date == date(2026, 11, 25)
    assert date(2026, 11, 18) not in {c.date for c in classes}

    for calendar_class in tuesdays:
        assert calendar_class.start_time == time(18, 30)
        assert calendar_class.end_time == time(21, 30)
        assert calendar_class.modality == "in_person"
        assert calendar_class.title == "Clase presencial"
        assert calendar_class.location is None
        assert calendar_class.meeting_url is None

    for calendar_class in wednesdays:
        assert calendar_class.start_time == time(18, 30)
        assert calendar_class.end_time == time(21, 0)
        assert calendar_class.modality == "virtual"
        assert calendar_class.title == "Clase virtual"
        assert calendar_class.location is None
        assert calendar_class.meeting_url is None

    expected_dates = set()
    day = date(2026, 8, 1)
    while day <= date(2026, 11, 28):
        if day.isoweekday() in (2, 3) and day != date(2026, 11, 18):
            expected_dates.add(day)
        day += timedelta(days=1)
    assert {calendar_class.date for calendar_class in classes} == expected_dates


async def test_seed_real_activities():
    expected = {
        "Primera entrega: Informe/Estudio Inicial": (
            date(2026, 9, 2),
            time(23, 0),
        ),
        "Planificación y Seguimiento del Proyecto: Sprint 0": (
            date(2026, 9, 16),
            time(23, 0),
        ),
        "Planificación y Seguimiento del Proyecto: Sprint 1 + Definición del producto": (
            date(2026, 9, 30),
            time(23, 0),
        ),
        "Planificación y Seguimiento del Proyecto: Sprint 2 + Definición del producto": (
            date(2026, 10, 14),
            time(23, 0),
        ),
        "Planificación y Seguimiento del Proyecto: Sprint 3": (
            date(2026, 10, 30),
            time(18, 0),
        ),
        "Planificación y Seguimiento del Proyecto: Sprint 4": (
            date(2026, 11, 13),
            time(18, 0),
        ),
    }
    activities = {activity.title: activity for activity in await _all(Activity)}
    assert set(activities) == set(expected)
    for title, (due_date, due_time) in expected.items():
        activity = activities[title]
        assert activity.due_date == due_date
        assert activity.due_time == due_time
        assert activity.link_required is True
        assert activity.description is None

    calendars = {calendar.id_calendar: calendar for calendar in await _all(Calendar)}
    section_years = {
        section_year.id_section_year: section_year
        for section_year in await _all(SectionYear)
    }
    for activity in activities.values():
        section_year = section_years[calendars[activity.id_calendar].id_section_year]
        assert (section_year.section.name, section_year.year) == ("3K1", 2026)


async def test_seed_real_deliveries():
    deliveries = await _all(Delivery)
    projects = await _all(Project)
    activities = await _all(Activity)

    assert len(deliveries) == len(projects) * len(activities) == 108
    assert len({(d.id_project, d.id_activity) for d in deliveries}) == 108
    assert {delivery.status.code for delivery in deliveries} == {
        "requested",
        "pending_approval",
        "pending_modification",
        "approved",
    }

    with_link = [delivery for delivery in deliveries if delivery.link]
    without_link = [delivery for delivery in deliveries if not delivery.link]
    assert with_link
    assert without_link
    assert all(
        delivery.submitted_at is not None and delivery.updated_at is not None
        for delivery in with_link
    )

    for activity in activities:
        linked = [
            delivery
            for delivery in deliveries
            if delivery.id_activity == activity.id_activity and delivery.link
        ]
        empty = [
            delivery
            for delivery in deliveries
            if delivery.id_activity == activity.id_activity and not delivery.link
        ]
        assert linked
        assert empty

    patterns: dict[int, set[str]] = {}
    for delivery in deliveries:
        patterns.setdefault(delivery.id_project, set()).add(delivery.status.code)
    assert len({frozenset(codes) for codes in patterns.values()}) > 1

    sprint_4 = next(
        activity
        for activity in activities
        if activity.title.endswith("Sprint 4")
    )
    assert any(
        delivery.id_activity == sprint_4.id_activity and delivery.link
        for delivery in deliveries
    )

    grades = await _all(DeliveryGrade)
    delivery_ids = {delivery.id_delivery for delivery in deliveries}
    assert {"activity", "follow_up"} <= {grade.category for grade in grades}
    assert all(grade.id_delivery in delivery_ids for grade in grades)


