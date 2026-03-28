import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def scraping_job() -> None:
    """Wrapper that imports lazily to avoid circular imports at startup."""
    from app.services.scraping_service import run_scraping

    logger.info("Scheduled scraping started")
    try:
        summary = await run_scraping()
        logger.info("Scheduled scraping done: %s", summary)
    except Exception as e:
        logger.error("Scheduled scraping error: %s", e)
