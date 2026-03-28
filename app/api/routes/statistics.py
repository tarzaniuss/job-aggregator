from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.technology import Technology
from app.models.vacancy import Vacancy, vacancy_technologies
from app.schemas.statistics import CategoryStat, SalaryStat, TechnologyStat, TrendPoint

router = APIRouter()


@router.get("/categories", response_model=list[CategoryStat])
async def categories_stats(db: DbSession):
    result = await db.execute(
        select(Vacancy.category, func.count(Vacancy.id).label("count"))
        .where(Vacancy.is_active.is_(True))
        .group_by(Vacancy.category)
        .order_by(func.count(Vacancy.id).desc())
    )
    return [CategoryStat(category=row[0], count=row[1]) for row in result.all()]


@router.get("/technologies", response_model=list[TechnologyStat])
async def technologies_stats(db: DbSession, limit: int = 20):
    limit = min(limit, 100)
    result = await db.execute(
        select(Technology.name, func.count(vacancy_technologies.c.vacancy_id).label("count"))
        .join(vacancy_technologies, Technology.id == vacancy_technologies.c.technology_id)
        .group_by(Technology.name)
        .order_by(func.count(vacancy_technologies.c.vacancy_id).desc())
        .limit(limit)
    )
    return [TechnologyStat(name=row[0], count=row[1]) for row in result.all()]


@router.get("/salaries", response_model=list[SalaryStat])
async def salaries_stats(db: DbSession):
    result = await db.execute(
        select(
            Vacancy.category,
            func.avg(Vacancy.salary_min).label("avg_min"),
            func.avg(Vacancy.salary_max).label("avg_max"),
            Vacancy.salary_currency,
        )
        .where(Vacancy.is_active.is_(True))
        .where(Vacancy.salary_min.isnot(None))
        .where(Vacancy.salary_currency == "USD")
        .group_by(Vacancy.category, Vacancy.salary_currency)
        .order_by(Vacancy.category)
    )
    return [
        SalaryStat(
            category=row[0],
            avg_min=round(row[1], 0) if row[1] else None,
            avg_max=round(row[2], 0) if row[2] else None,
            currency=row[3],
        )
        for row in result.all()
    ]


@router.get("/trends", response_model=list[TrendPoint])
async def trends_stats(db: DbSession, days: int = 30):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            func.date(Vacancy.scraped_at).label("date"),
            func.count(Vacancy.id).label("count"),
        )
        .where(Vacancy.is_active.is_(True))
        .where(Vacancy.scraped_at >= since)
        .group_by(func.date(Vacancy.scraped_at))
        .order_by(func.date(Vacancy.scraped_at))
    )
    return [TrendPoint(date=str(row[0]), count=row[1]) for row in result.all()]
