from collections import defaultdict

from sqlalchemy import func
from sqlmodel import select

from models import Project, ProjectTechnology, Section, SectionYear, Technology
from schemas.project_technology_statistics import (
    ProjectTechnologyStatisticsPublic,
    SectionTechnologyStatisticsPublic,
    TechnologyStatisticsTotalsPublic,
    TechnologyTotalPublic,
    TechnologyUsagePublic,
    YearTechnologyStatisticsPublic,
)


def _percentage(count: int, total: int) -> float | None:
    if not total:
        return None
    return round(count * 100 / total, 2)


def _usage(items) -> list[TechnologyUsagePublic]:
    return [
        TechnologyUsagePublic(
            id_technology=id_technology,
            name=name,
            projects_count=count,
            projects_percentage=_percentage(count, denominator),
        )
        for id_technology, name, count, denominator in items
    ]


async def build_project_technology_statistics(
    db,
) -> ProjectTechnologyStatisticsPublic:
    """Estadísticas agregadas de tecnologías por año y curso lectivo."""
    project_rows = (
        await db.exec(
            select(
                SectionYear,
                Section.name,
                func.count(Project.id_project),
            )
            .select_from(Project)
            .join(SectionYear, SectionYear.id_section_year == Project.id_section_year)
            .join(Section, Section.id_section == SectionYear.id_section)
            .where(SectionYear.is_generic == False)  # noqa: E712
            .group_by(SectionYear.id_section_year, Section.name)
        )
    ).all()
    projects_by_section = {
        sy.id_section_year: count for sy, _, count in project_rows
    }
    section_years = {sy.id_section_year: sy for sy, _, _ in project_rows}
    section_names = {sy.id_section_year: name for sy, name, _ in project_rows}

    with_tech_rows = (
        await db.exec(
            select(
                Project.id_section_year,
                func.count(func.distinct(Project.id_project)),
            )
            .select_from(ProjectTechnology)
            .join(Project, Project.id_project == ProjectTechnology.id_project)
            .join(SectionYear, SectionYear.id_section_year == Project.id_section_year)
            .where(SectionYear.is_generic == False)  # noqa: E712
            .group_by(Project.id_section_year)
        )
    ).all()
    with_tech_by_section = {id_sy: count for id_sy, count in with_tech_rows}

    usage_rows = (
        await db.exec(
            select(
                Project.id_section_year,
                Technology.id_technology,
                Technology.name,
                func.count(func.distinct(Project.id_project)),
            )
            .select_from(ProjectTechnology)
            .join(Project, Project.id_project == ProjectTechnology.id_project)
            .join(SectionYear, SectionYear.id_section_year == Project.id_section_year)
            .join(
                Technology,
                Technology.id_technology == ProjectTechnology.id_technology,
            )
            .where(SectionYear.is_generic == False)  # noqa: E712
            .group_by(
                Project.id_section_year,
                Technology.id_technology,
                Technology.name,
            )
        )
    ).all()
    usage_by_section: dict[int, list[tuple[int, str, int]]] = defaultdict(list)
    for id_section_year, id_technology, name, count in usage_rows:
        usage_by_section[id_section_year].append((id_technology, name, count))

    global_rows = (
        await db.exec(
            select(
                Technology.id_technology,
                Technology.name,
                func.count(func.distinct(Project.id_project)),
            )
            .select_from(ProjectTechnology)
            .join(Project, Project.id_project == ProjectTechnology.id_project)
            .join(SectionYear, SectionYear.id_section_year == Project.id_section_year)
            .join(
                Technology,
                Technology.id_technology == ProjectTechnology.id_technology,
            )
            .where(SectionYear.is_generic == False)  # noqa: E712
            .group_by(Technology.id_technology, Technology.name)
        )
    ).all()

    years: dict[int, list[int]] = defaultdict(list)
    for sy in section_years.values():
        years[sy.year].append(sy.id_section_year)

    public_years: list[YearTechnologyStatisticsPublic] = []
    for year in sorted(years):
        section_ids = sorted(
            years[year],
            key=lambda id_sy: (section_names[id_sy], id_sy),
        )
        sections: list[SectionTechnologyStatisticsPublic] = []
        year_usage: dict[int, tuple[str, int]] = {}
        for id_section_year in section_ids:
            sy = section_years[id_section_year]
            denominator = with_tech_by_section.get(id_section_year, 0)
            usage = [
                (
                    id_technology,
                    name,
                    count,
                    denominator,
                )
                for id_technology, name, count in sorted(
                    usage_by_section.get(id_section_year, []),
                    key=lambda item: (-item[2], item[1], item[0]),
                )
            ]
            sections.append(
                SectionTechnologyStatisticsPublic(
                    id_section_year=id_section_year,
                    year=year,
                    id_section=sy.id_section,
                    section_name=section_names[id_section_year],
                    projects_total=projects_by_section.get(id_section_year, 0),
                    projects_with_technologies=denominator,
                    technologies=_usage(usage),
                )
            )
            for id_technology, name, count in usage_by_section.get(
                id_section_year, []
            ):
                previous = year_usage.get(id_technology)
                year_usage[id_technology] = (
                    name,
                    (previous[1] if previous else 0) + count,
                )

        year_projects_total = sum(
            projects_by_section.get(id_sy, 0) for id_sy in section_ids
        )
        year_with_tech = sum(
            with_tech_by_section.get(id_sy, 0) for id_sy in section_ids
        )
        year_technologies = _usage(
            [
                (id_technology, name, count, year_with_tech)
                for id_technology, (name, count) in year_usage.items()
            ]
        )
        year_technologies.sort(
            key=lambda item: (-item.projects_count, item.name, item.id_technology)
        )
        public_years.append(
            YearTechnologyStatisticsPublic(
                year=year,
                projects_total=year_projects_total,
                projects_with_technologies=year_with_tech,
                technologies=year_technologies,
                sections=sections,
            )
        )

    technologies = [
        TechnologyTotalPublic(
            id_technology=id_technology,
            name=name,
            projects_count=count,
        )
        for id_technology, name, count in sorted(
            global_rows,
            key=lambda item: (-item[2], item[1], item[0]),
        )
    ]
    return ProjectTechnologyStatisticsPublic(
        totals=TechnologyStatisticsTotalsPublic(
            projects_total=sum(projects_by_section.values()),
            projects_with_technologies=sum(with_tech_by_section.values()),
        ),
        years=public_years,
        technologies=technologies,
    )
