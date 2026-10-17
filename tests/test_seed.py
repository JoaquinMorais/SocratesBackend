from sqlalchemy import text
from sqlmodel import SQLModel, func, select

from config.database import SessionLocal
from models import (
    Professor,
    ProfessorSectionYear,
    Project,
    Section,
    SectionYear,
    Status,
    Student,
    StudentProject,
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
    assert ("project", "active") in pairs
    assert ("student_project", "active") in pairs
    assert {s.ambito for s in statuses} <= {"project", "student_project"}


async def test_seed_projects_and_memberships_have_status_of_their_ambito():
    await _load_full_seed()
    async with SessionLocal() as session:
        projects = (await session.exec(select(Project))).all()
        memberships = (await session.exec(select(StudentProject))).all()
    assert all(p.status.ambito == "project" for p in projects)
    assert all(m.status.ambito == "student_project" for m in memberships)


async def test_seed_emails_and_legajos_are_unique():
    await _load_full_seed()
    async with SessionLocal() as session:
        professors = (await session.exec(select(Professor))).all()
        students = (await session.exec(select(Student))).all()
        legajos = (await session.exec(select(Student.id_student))).all()
    mails = [p.mail for p in professors]
    assert len(mails) == len(set(mails))
    student_legajos = [s.user.legajo for s in students]
    assert len(student_legajos) == len(set(student_legajos))
    assert len(legajos) == len(set(legajos))


async def test_seed_memberships_are_unique_per_section_year():
    await _load_full_seed()
    async with SessionLocal() as session:
        rows = (
            await session.exec(
                select(StudentProject.id_student, Project.id_section_year).join(
                    Project, Project.id_project == StudentProject.id_project
                )
            )
        ).all()
    seen: set[tuple[int, int]] = set()
    for id_student, id_section_year in rows:
        key = (id_student, id_section_year)
        assert key not in seen, f"el alumno {id_student} está dos veces en el curso lectivo {id_section_year}"
        seen.add(key)


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
