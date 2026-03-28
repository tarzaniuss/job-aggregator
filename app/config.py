import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/jobsdb"
    groq_api_key: str = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.groq_api_key:
            logger.warning("GROQ_API_KEY is not set — AI enrichment will be disabled")
    scraping_interval_hours: int = 4
    log_level: str = "INFO"
    dou_max_pages: int = 0    # 0 = unlimited; ~40 vacancies per page
    djinni_max_pages: int = 0  # 0 = unlimited; ~15-20 vacancies per page
    dou_categories: list[str] = ["Python", "Node.js", "Data Science"]
    djinni_keywords: dict[str, str] = {
        "python": "Python",
        "node.js": "Node.js",
        "Data Science": "Data Science",
    }


settings = Settings()
