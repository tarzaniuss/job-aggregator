import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.technology import Technology
from app.models.vacancy import Vacancy
from app.models.vacancy import vacancy_technologies as vt_table
from app.scrapers.base import RawVacancy
from app.scrapers.djinni import KEYWORD_TO_CATEGORY, DjinniScraper
from app.scrapers.dou import CATEGORIES as DOU_CATEGORIES
from app.scrapers.dou import DouScraper
from app.services.ai_service import AIResult, analyze_vacancy

logger = logging.getLogger(__name__)


async def _get_or_create_technology(session: AsyncSession, name: str) -> Technology:
    """Return an existing Technology row or create one if it does not exist yet.

    Uses INSERT ... ON CONFLICT DO NOTHING to avoid race conditions when
    multiple coroutines try to create the same technology simultaneously.
    """
    name = name.strip()
    await session.execute(
        pg_insert(Technology)
        .values(name=name)
        .on_conflict_do_nothing(index_elements=["name"])
    )
    result = await session.execute(select(Technology).where(Technology.name == name))
    return result.scalar_one()


async def _save_vacancy(
    session: AsyncSession,
    raw: RawVacancy,
    ai: Optional[AIResult],
) -> bool:
    """Save a vacancy to the DB, deduplicating by URL.

    HTML-parsed fields (e.g. english_level from Djinni) take priority over AI ones.
    Returns True if a new row was inserted, False if the URL already existed.
    """
    result = await session.execute(select(Vacancy).where(Vacancy.url == raw.url))
    if result.scalar_one_or_none():
        return False

    experience_years = raw.experience_years
    english_level = raw.english_level
    responsibilities_summary = None
    required_skills_summary = None
    technologies_names: list[str] = []

    if ai:
        technologies_names = ai.technologies
        responsibilities_summary = ai.responsibilities_summary
        required_skills_summary = ai.required_skills_summary
        if experience_years is None:
            experience_years = ai.experience_years
        if english_level is None:
            english_level = ai.english_level

    vacancy = Vacancy(
        url=raw.url,
        source=raw.source,
        category=raw.category,
        title=raw.title,
        company=raw.company,
        location=raw.location,
        salary_min=raw.salary_min,
        salary_max=raw.salary_max,
        salary_currency=raw.salary_currency,
        description=raw.description,
        experience_years=experience_years,
        english_level=english_level,
        responsibilities_summary=responsibilities_summary,
        required_skills_summary=required_skills_summary,
        published_at=raw.published_at,
        scraped_at=datetime.now(timezone.utc),
    )
    session.add(vacancy)
    await session.flush()

    for name in technologies_names:
        if name:
            tech = await _get_or_create_technology(session, name)
            await session.execute(
                pg_insert(vt_table)
                .values(vacancy_id=vacancy.id, technology_id=tech.id)
                .on_conflict_do_nothing()
            )

    return True


async def _process_and_save(
    raw_list: list[RawVacancy],
    source_label: str,
) -> tuple[int, int, int]:
    """Run LLM analysis then DB save for each vacancy in the list.

    Three phases:
      1. Batch dedup — single DB query to skip already-known URLs.
      2. Concurrent LLM — all fresh vacancies analyzed in parallel;
         each call picks the least-loaded model via _pick_model().
      3. Sequential saves — one session per vacancy so commits are isolated
         and progress is visible in real time.

    Returns (new, skipped, errors).
    """
    if not raw_list:
        return 0, 0, 0

    # Phase 1: batch dedup — find which URLs are already in DB
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(Vacancy.url).where(Vacancy.url.in_([r.url for r in raw_list]))
        )
        known_urls = frozenset(row[0] for row in existing.all())

    fresh = [r for r in raw_list if r.url not in known_urls]
    skipped = len(raw_list) - len(fresh)
    logger.info("%s: %d total, %d already in DB, %d to process", source_label, len(raw_list), skipped, len(fresh))

    if not fresh:
        return 0, skipped, 0

    # LLM + save in one coroutine per vacancy — save immediately after LLM responds,
    # no waiting for the whole batch. The semaphore in analyze_vacancy limits
    # concurrent Groq calls to 4 globally.
    new = 0
    errors = 0

    async def process_one(raw: RawVacancy) -> tuple[str, bool]:
        """Returns ("new", True), ("skipped", False), or ("error", False)."""
        t0 = time.perf_counter()
        try:
            ai = await analyze_vacancy(raw.description, raw.source)
            elapsed = time.perf_counter() - t0
            async with AsyncSessionLocal() as session:
                try:
                    inserted = await _save_vacancy(session, raw, ai)
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    return "skipped", False
            if inserted:
                logger.info(
                    "%s: saved (llm=%.2fs) — %s @ %s",
                    source_label, elapsed, raw.title, raw.company,
                )
                return "new", True
            return "skipped", False
        except Exception as e:
            logger.warning("Failed to process %s vacancy %s: %s", source_label, raw.url, e)
            return "error", False

    results = await asyncio.gather(*[process_one(r) for r in fresh])
    for status, _ in results:
        if status == "new":
            new += 1
        elif status == "skipped":
            skipped += 1
        else:
            errors += 1

    return new, skipped, errors


async def run_scraping() -> dict:
    """
    Main scraping orchestration. Run all scrapers, save results.

    DOU categories and Djinni keywords are scraped concurrently via
    asyncio.gather. Each batch is processed with concurrent LLM calls
    (one per fresh vacancy) that self-regulate via ModelScheduler.

    Returns a summary dict.
    """
    logger.info("run_scraping: started")
    # Each category gets its own scraper instance — they must NOT share a
    # requests.Session because DOU stores the active category filter in the
    # server-side Django session (tied to the session cookie). Sharing one
    # session across concurrent threads causes all categories to return the
    # same (first) category's vacancies.
    djinni_scraper = DjinniScraper()

    # Verify DB connectivity before doing any work
    async with AsyncSessionLocal() as session:
        try:
            count = await session.scalar(select(func.count()).select_from(Vacancy))
            logger.info("DB OK — vacancies table exists, current row count: %d", count)
        except Exception as e:
            logger.error(
                "DB error — tables may not exist. Did you run 'alembic upgrade head'? %s",
                e,
            )
            return {"new": 0, "skipped": 0, "errors": 1}

    loop = asyncio.get_event_loop()

    async def scrape_dou(category: str) -> tuple[int, int, int]:
        try:
            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Vacancy.url).where(Vacancy.source == "DOU")
                )
                known_urls = frozenset(row[0] for row in existing.all())

            logger.info("DOU [%s]: %d URLs already in DB — fetching list pages...", category, len(known_urls))

            scraper = DouScraper()  # isolated session per category
            raw_list = await loop.run_in_executor(
                None,
                scraper.scrape,
                category,
                known_urls,
                settings.dou_max_pages,
            )
            logger.info("DOU [%s]: scraping done, processing %d vacancies...", category, len(raw_list))

            return await _process_and_save(raw_list, f"DOU [{category}]")
        except Exception as e:
            logger.error("DOU scraping failed for category %s: %s", category, e)
            return 0, 0, 1

    async def scrape_djinni(keyword: str) -> tuple[int, int, int]:
        try:
            logger.info("Djinni [%s]: fetching list pages...", keyword)
            raw_list = await loop.run_in_executor(
                None, djinni_scraper.scrape, keyword, settings.djinni_max_pages
            )
            logger.info("Djinni [%s]: scraping done, processing %d vacancies...", keyword, len(raw_list))

            return await _process_and_save(raw_list, f"Djinni [{keyword}]")
        except Exception as e:
            logger.error("Djinni scraping failed for keyword %s: %s", keyword, e)
            return 0, 0, 1

    tasks = (
        [scrape_dou(cat) for cat in DOU_CATEGORIES]
        + [scrape_djinni(kw) for kw in KEYWORD_TO_CATEGORY]
    )
    results = await asyncio.gather(*tasks)

    total_new = sum(r[0] for r in results)
    total_skipped = sum(r[1] for r in results)
    total_errors = sum(r[2] for r in results)

    summary = {"new": total_new, "skipped": total_skipped, "errors": total_errors}
    logger.info("Scraping complete: %s", summary)
    return summary
