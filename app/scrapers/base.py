import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


@dataclass
class RawVacancy:
    """Intermediate DTO produced by a scraper before DB persistence."""

    url: str
    source: str
    category: str
    title: str = ""
    company: str = ""
    location: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = None
    description: str = ""
    experience_years: Optional[int] = None
    english_level: Optional[str] = None
    published_at: Optional[datetime] = None


class BaseScraper:
    """Base class for all site-specific scrapers."""

    source: str = ""
    delay: float = 1.5

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Perform a GET request using the shared session with rate-limit delay.

        Returns None on any HTTP or network error instead of raising.
        """
        try:
            response = self.session.get(url, timeout=15, **kwargs)
            response.raise_for_status()
            time.sleep(self.delay)
            return response
        except requests.RequestException as e:
            logger.warning("HTTP error fetching %s: %s", url, e)
            return None

    def post(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Perform a POST request using the shared session with rate-limit delay.

        Returns None on any HTTP or network error instead of raising.
        """
        try:
            response = self.session.post(url, timeout=15, **kwargs)
            response.raise_for_status()
            time.sleep(self.delay)
            return response
        except requests.RequestException as e:
            logger.warning("HTTP error posting %s: %s", url, e)
            return None

    # Subclasses implement their own scrape() method.
    # Signature varies per source, but all return list[RawVacancy].
