# Job Aggregator

REST API that scrapes developer job listings from [DOU.ua](https://jobs.dou.ua) and [Djinni.co](https://djinni.co), enriches them with AI-extracted insights (technologies, summaries, experience level), and serves the data through a filterable API with analytics.

## Tech Stack

- **API:** FastAPI + Uvicorn
- **Database:** PostgreSQL + SQLAlchemy (async) + Alembic
- **Scraping:** Requests + BeautifulSoup
- **AI Enrichment:** Groq API (multi-model rotation with rate-limit handling)
- **Scheduler:** APScheduler (runs inside FastAPI process)
- **Infrastructure:** Docker + Docker Compose
- **Tests:** pytest + httpx + pytest-asyncio

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env — set GROQ_API_KEY and Postgres credentials

docker compose up -d --build
```

The API will be available at `http://localhost:8000`. Swagger docs at `http://localhost:8000/docs`.

### Local Development

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env — set DATABASE_URL and GROQ_API_KEY

alembic upgrade head
uvicorn main:app --reload
```

## API Endpoints

### Vacancies

| Method | Path | Description |
|--------|------|-------------|
| GET | `/vacancies` | List vacancies with filters |
| GET | `/vacancies/{id}` | Vacancy details with technologies |

**Query parameters for `/vacancies`:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `category` | string | Filter by category (Python, Node.js, Data Science) |
| `technology` | string | Filter by technology name |
| `salary_min` | int | Minimum salary |
| `salary_max` | int | Maximum salary |
| `source` | string | DOU or Djinni |
| `experience_years` | int | Max years of experience required |
| `limit` | int | Results per page (default 20, max 100) |
| `offset` | int | Pagination offset |

### Statistics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/statistics/categories` | Vacancy count by category |
| GET | `/statistics/technologies?limit=20` | Most demanded technologies |
| GET | `/statistics/salaries` | Average salary ranges by category |
| GET | `/statistics/trends?days=30` | New vacancies per day |

### Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/analytics/stack-demand?category=Python&limit=20` | Technology pairs that appear together most often |
| GET | `/analytics/experience-distribution?category=Python` | Vacancy count by experience level |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/scrape` | Manually trigger scraping |

## Project Structure

```
app/
  api/
    routes/
      vacancies.py        # CRUD endpoints
      statistics.py       # Aggregated stats
      analytics.py        # Stack demand, experience distribution
    deps.py               # Dependency injection (DB session)
  models/
    vacancy.py            # Vacancy + M2M junction table
    technology.py          # Technology model
  schemas/
    vacancy.py            # Pydantic response models
    statistics.py         # Stats response models
  scrapers/
    base.py               # Base scraper (HTTP session, rate limiting)
    dou.py                # DOU.ua scraper (XHR pagination + description fetch)
    djinni.py             # Djinni.co scraper (JSON-LD parsing)
  services/
    ai_service.py         # Groq LLM integration (4-model rotation)
    scraping_service.py   # Orchestration: scrape -> enrich -> save
  config.py               # Settings from .env
  database.py             # Async engine + session factory
  scheduler.py            # APScheduler setup
alembic/                  # Database migrations
tests/                    # pytest test suite
main.py                   # FastAPI entrypoint
```

## How It Works

1. **Scraping** — DOU (XHR pagination) and Djinni (JSON-LD parsing) are scraped concurrently per category
2. **AI Enrichment** — Each vacancy description is sent to Groq LLM which extracts: technologies, experience level, English requirement, responsibilities and skills summaries
3. **Multi-model rotation** — 4 Groq models are rotated with per-model rate limiting and automatic penalization on errors
4. **Deduplication** — Unique constraint on URL prevents duplicates; known URLs are skipped before description fetch
5. **Scheduling** — APScheduler runs the full pipeline every N hours (configurable)

## Running Tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `GROQ_API_KEY` | — | Required for AI enrichment |
| `SCRAPING_INTERVAL_HOURS` | `4` | Auto-scraping interval |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DOU_MAX_PAGES` | `0` | Page limit for DOU (0 = unlimited) |
| `DJINNI_MAX_PAGES` | `0` | Page limit for Djinni (0 = unlimited) |
