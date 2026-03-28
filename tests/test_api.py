"""Integration tests for FastAPI endpoints."""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.technology import Technology
from app.models.vacancy import Vacancy


@pytest_asyncio.fixture
async def sample_vacancy(db_session):
    result = await db_session.execute(select(Technology).where(Technology.name == "Django"))
    tech = result.scalar_one_or_none()
    if not tech:
        tech = Technology(name="Django")
        db_session.add(tech)
        await db_session.flush()

    result2 = await db_session.execute(select(Vacancy).where(Vacancy.url == "https://jobs.dou.ua/test/1/"))
    existing = result2.scalar_one_or_none()
    if existing:
        return existing

    v = Vacancy(
        url="https://jobs.dou.ua/test/1/",
        source="DOU",
        category="Python",
        title="Senior Python Developer",
        company="TestCorp",
        location="віддалено",
        salary_min=3000,
        salary_max=5000,
        salary_currency="USD",
        description="Full description here.",
        experience_years=3,
        english_level="Upper-Intermediate",
        responsibilities_summary="Develop APIs",
        required_skills_summary="Python, Django",
        is_active=True,
    )
    v.technologies.append(tech)
    db_session.add(v)
    await db_session.commit()
    return v


@pytest.mark.asyncio
async def test_list_vacancies_empty(client):
    response = await client.get("/vacancies")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_list_vacancies_with_data(client, sample_vacancy):
    response = await client.get("/vacancies")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    urls = [item["url"] for item in data["items"]]
    assert "https://jobs.dou.ua/test/1/" in urls


@pytest.mark.asyncio
async def test_filter_by_category(client, sample_vacancy):
    response = await client.get("/vacancies?category=Python")
    assert response.status_code == 200
    data = response.json()
    assert all(item["category"] == "Python" for item in data["items"])


@pytest.mark.asyncio
async def test_filter_by_technology(client, sample_vacancy):
    response = await client.get("/vacancies?technology=Django")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_filter_by_salary(client, sample_vacancy):
    response = await client.get("/vacancies?salary_min=2000&salary_max=6000")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_vacancy_detail(client, sample_vacancy):
    response = await client.get(f"/vacancies/{sample_vacancy.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == sample_vacancy.id
    assert data["title"] == "Senior Python Developer"
    assert any(t["name"] == "Django" for t in data["technologies"])


@pytest.mark.asyncio
async def test_get_vacancy_not_found(client):
    response = await client.get("/vacancies/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_statistics_categories(client, sample_vacancy):
    response = await client.get("/statistics/categories")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    categories = [item["category"] for item in data]
    assert "Python" in categories


@pytest.mark.asyncio
async def test_statistics_technologies(client, sample_vacancy):
    response = await client.get("/statistics/technologies")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    names = [item["name"] for item in data]
    assert "Django" in names


@pytest.mark.asyncio
async def test_statistics_salaries(client, sample_vacancy):
    response = await client.get("/statistics/salaries")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_statistics_trends(client, sample_vacancy):
    response = await client.get("/statistics/trends?days=30")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_analytics_stack_demand(client, sample_vacancy):
    response = await client.get("/analytics/stack-demand")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_analytics_stack_demand_with_category(client, sample_vacancy):
    response = await client.get("/analytics/stack-demand?category=python")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_analytics_experience_distribution(client, sample_vacancy):
    response = await client.get("/analytics/experience-distribution")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    levels = [item["level"] for item in data]
    assert "Middle (3-4 years)" in levels  # sample_vacancy has experience_years=3


@pytest.mark.asyncio
async def test_analytics_experience_distribution_case_insensitive(client, sample_vacancy):
    response = await client.get("/analytics/experience-distribution?category=python")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1  # sample_vacancy has category="Python"
