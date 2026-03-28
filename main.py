import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import analytics, statistics, vacancies
from app.config import settings
from app.scheduler import scheduler, scraping_job

logging.basicConfig(level=settings.log_level)
# Silence noisy SDK loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("groq").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the APScheduler on startup and shut it down cleanly on exit."""
    scheduler.add_job(
        scraping_job,
        "interval",
        hours=settings.scraping_interval_hours,
        id="scraping",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (interval: %dh)", settings.scraping_interval_hours)
    try:
        yield
    finally:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


app = FastAPI(title="Job Aggregator", version="1.0.0", lifespan=lifespan)

app.include_router(vacancies.router, prefix="/vacancies", tags=["vacancies"])
app.include_router(statistics.router, prefix="/statistics", tags=["statistics"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])


@app.post("/admin/scrape", tags=["admin"])
async def trigger_scrape():
    """Manually trigger a scraping run (for development/testing)."""
    from app.services.scraping_service import run_scraping

    summary = await run_scraping()
    return {"status": "done", **summary}
