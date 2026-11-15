from sqlmodel import SQLModel


class TechnologyStatisticsTotalsPublic(SQLModel):
    projects_total: int
    projects_with_technologies: int


class TechnologyUsagePublic(SQLModel):
    id_technology: int
    name: str
    projects_count: int
    projects_percentage: float | None = None


class SectionTechnologyStatisticsPublic(SQLModel):
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    projects_total: int
    projects_with_technologies: int
    technologies: list[TechnologyUsagePublic]


class YearTechnologyStatisticsPublic(SQLModel):
    year: int
    projects_total: int
    projects_with_technologies: int
    technologies: list[TechnologyUsagePublic]
    sections: list[SectionTechnologyStatisticsPublic]


class TechnologyTotalPublic(SQLModel):
    id_technology: int
    name: str
    projects_count: int


class ProjectTechnologyStatisticsPublic(SQLModel):
    totals: TechnologyStatisticsTotalsPublic
    years: list[YearTechnologyStatisticsPublic]
    technologies: list[TechnologyTotalPublic]
