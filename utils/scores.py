from fastapi import HTTPException, status
from sqlmodel import col, select

from models import Score, SectionYearScore
from schemas.score import (
    SectionYearScorePublic,
    SectionYearScoresUpdate,
    SectionYearScoreValue,
)

DEFAULT_SCORES = (
    {
        "code": "excellent",
        "name": "Excelente",
        "sort_order": 1,
        "default_value": 100,
    },
    {
        "code": "very_good_plus",
        "name": "Muy Bueno +",
        "sort_order": 2,
        "default_value": 90,
    },
    {
        "code": "very_good",
        "name": "Muy Bueno",
        "sort_order": 3,
        "default_value": 80,
    },
    {
        "code": "good",
        "name": "Bueno",
        "sort_order": 4,
        "default_value": 65,
    },
    {
        "code": "regular",
        "name": "Regular",
        "sort_order": 5,
        "default_value": 55,
    },
    {
        "code": "incomplete",
        "name": "Incompleto",
        "sort_order": 6,
        "default_value": 30,
    },
)


def to_public(row: SectionYearScore) -> SectionYearScorePublic:
    return SectionYearScorePublic(
        id_section_year_score=row.id_section_year_score,
        id_score=row.id_score,
        code=row.score.code,
        name=row.score.name,
        value=row.value,
    )


async def ensure_scores(db) -> dict[str, Score]:
    every = {score.code: score for score in (await db.exec(select(Score))).all()}
    for item in DEFAULT_SCORES:
        if item["code"] not in every:
            score = Score(**item)
            db.add(score)
            every[item["code"]] = score
    await db.flush()
    return every


async def ensure_section_year_scores(db, id_section_year: int) -> None:
    scores = await ensure_scores(db)
    existing = {
        row.id_score
        for row in (
            await db.exec(
                select(SectionYearScore).where(
                    SectionYearScore.id_section_year == id_section_year
                )
            )
        ).all()
    }
    for score in scores.values():
        if score.id_score not in existing:
            db.add(
                SectionYearScore(
                    id_section_year=id_section_year,
                    id_score=score.id_score,
                    value=score.default_value,
                )
            )
    await db.flush()


async def list_section_year_scores(db, id_section_year: int) -> list[SectionYearScore]:
    await ensure_section_year_scores(db, id_section_year)
    await db.commit()
    return list(
        (
            await db.exec(
                select(SectionYearScore)
                .join(Score, Score.id_score == SectionYearScore.id_score)
                .where(SectionYearScore.id_section_year == id_section_year)
                .order_by(col(Score.sort_order), col(Score.id_score))
            )
        ).all()
    )


async def update_section_year_scores(
    db, id_section_year: int, data: SectionYearScoresUpdate
) -> list[SectionYearScore]:
    await ensure_section_year_scores(db, id_section_year)
    scores = {score.code: score for score in (await db.exec(select(Score))).all()}
    rows = {
        row.score.code: row
        for row in (
            await db.exec(
                select(SectionYearScore)
                .join(Score, Score.id_score == SectionYearScore.id_score)
                .where(SectionYearScore.id_section_year == id_section_year)
            )
        ).all()
    }
    for item in data.scores:
        if item.code not in scores:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown score code: {item.code}",
            )
        rows[item.code].value = item.value
        db.add(rows[item.code])
    await db.commit()
    return await list_section_year_scores(db, id_section_year)
