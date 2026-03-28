from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models.technology import Technology
from app.models.vacancy import Vacancy, vacancy_technologies
from app.schemas.vacancy import VacancyDetail, VacancyListResponse

router = APIRouter()


@router.get("", response_model=VacancyListResponse)
async def list_vacancies(
    db: DbSession,
    category: Optional[str] = None,
    technology: Optional[str] = None,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    source: Optional[str] = None,
    experience_years: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
):
    limit = min(limit, 100)
    query = select(Vacancy).where(Vacancy.is_active.is_(True))

    if category:
        query = query.where(func.lower(Vacancy.category) == category.lower())
    if source:
        query = query.where(Vacancy.source == source)
    if salary_min is not None:
        query = query.where(Vacancy.salary_min >= salary_min)
    if salary_max is not None:
        query = query.where(Vacancy.salary_max <= salary_max)
    if experience_years is not None:
        query = query.where(Vacancy.experience_years <= experience_years)
    if technology:
        subq = (
            select(vacancy_technologies.c.vacancy_id)
            .join(Technology, Technology.id == vacancy_technologies.c.technology_id)
            .where(func.lower(Technology.name) == technology.lower())
        )
        query = query.where(Vacancy.id.in_(subq))

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.order_by(Vacancy.scraped_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return VacancyListResponse(items=list(items), total=total)


@router.get("/{vacancy_id}", response_model=VacancyDetail)
async def get_vacancy(vacancy_id: int, db: DbSession):
    result = await db.execute(
        select(Vacancy)
        .where(Vacancy.id == vacancy_id)
        .options(selectinload(Vacancy.technologies))
    )
    vacancy = result.scalar_one_or_none()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return vacancy
