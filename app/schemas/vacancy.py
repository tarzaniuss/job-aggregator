from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TechnologyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class VacancyBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    source: str
    category: str
    title: str | None
    company: str | None
    location: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    experience_years: int | None
    english_level: str | None
    scraped_at: datetime
    published_at: datetime | None


class VacancyDetail(VacancyBrief):
    description: str | None
    responsibilities_summary: str | None
    required_skills_summary: str | None
    technologies: list[TechnologyOut] = []


class VacancyListResponse(BaseModel):
    items: list[VacancyBrief]
    total: int
