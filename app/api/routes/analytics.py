from typing import Optional

from fastapi import APIRouter
from sqlalchemy import case, func, select

from app.api.deps import DbSession
from app.models.technology import Technology
from app.models.vacancy import Vacancy, vacancy_technologies
from app.schemas.statistics import ExperienceBucket, StackPair

router = APIRouter()


@router.get("/stack-demand", response_model=list[StackPair])
async def stack_demand(
    db: DbSession,
    category: Optional[str] = None,
    limit: int = 20,
):
    """Top technology pairs that appear together in vacancies."""
    limit = min(limit, 100)

    # Self-join vacancy_technologies to get pairs within the same vacancy
    vt1 = vacancy_technologies.alias("vt1")
    vt2 = vacancy_technologies.alias("vt2")
    t1 = Technology.__table__.alias("t1")
    t2 = Technology.__table__.alias("t2")

    query = (
        select(
            t1.c.name.label("tech1"),
            t2.c.name.label("tech2"),
            func.count().label("count"),
        )
        .select_from(
            vt1.join(
                vt2,
                (vt1.c.vacancy_id == vt2.c.vacancy_id)
                & (vt1.c.technology_id < vt2.c.technology_id),
            )
            .join(t1, t1.c.id == vt1.c.technology_id)
            .join(t2, t2.c.id == vt2.c.technology_id)
        )
        .group_by(t1.c.name, t2.c.name)
        .order_by(func.count().desc())
        .limit(limit)
    )

    if category:
        query = query.join(
            Vacancy.__table__,
            Vacancy.__table__.c.id == vt1.c.vacancy_id,
        ).where(func.lower(Vacancy.__table__.c.category) == category.lower())

    result = await db.execute(query)
    return [StackPair(tech1=row[0], tech2=row[1], count=row[2]) for row in result.all()]


@router.get("/experience-distribution", response_model=list[ExperienceBucket])
async def experience_distribution(
    db: DbSession,
    category: Optional[str] = None,
):
    """Vacancy count by experience level buckets."""
    label = case(
        (Vacancy.experience_years.is_(None), "Not specified"),
        (Vacancy.experience_years == 0, "No experience"),
        (Vacancy.experience_years <= 2, "Junior (1-2 years)"),
        (Vacancy.experience_years <= 4, "Middle (3-4 years)"),
        else_="Senior (5+ years)",
    )

    query = (
        select(label.label("level"), func.count(Vacancy.id).label("count"))
        .where(Vacancy.is_active.is_(True))
        .group_by(label)
        .order_by(func.count(Vacancy.id).desc())
    )

    if category:
        query = query.where(func.lower(Vacancy.category) == category.lower())

    result = await db.execute(query)
    return [ExperienceBucket(level=row[0], count=row[1]) for row in result.all()]
