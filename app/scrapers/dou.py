import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from app.config import settings
from app.scrapers.base import BaseScraper, RawVacancy

logger = logging.getLogger(__name__)

MAIN_URL = "https://jobs.dou.ua/vacancies/"
XHR_URL = "https://jobs.dou.ua/vacancies/xhr-load/"


CATEGORIES = settings.dou_categories
PAGE_SIZE = 20
DESCRIPTION_WORKERS = 3  # concurrent description page fetches

MONTH_MAP = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}


def _parse_salary(text: str) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Parse '$2000–3750' or '$1500' into (min, max, currency)."""
    if not text:
        return None, None, None

    currency = None
    if "$" in text:
        currency = "USD"
    elif "грн" in text.lower() or "₴" in text:
        currency = "UAH"

    numbers = re.findall(r"\d+", text.replace("\xa0", "").replace(" ", ""))
    if not numbers:
        return None, None, currency

    nums = [int(n) for n in numbers]
    salary_min = nums[0]
    salary_max = nums[1] if len(nums) > 1 else nums[0]
    return salary_min, salary_max, currency


def _parse_date(text: str) -> Optional[datetime]:
    """Parse Ukrainian date like '5 березня' (uses current year)."""
    text = text.strip()
    parts = text.split()
    if len(parts) < 2:
        return None
    try:
        day = int(parts[0])
        month = MONTH_MAP.get(parts[1].lower())
        if month:
            return datetime(datetime.now(timezone.utc).year, month, day)
    except (ValueError, IndexError):
        pass
    return None


class DouScraper(BaseScraper):
    """Scraper for DOU.ua using the internal XHR pagination endpoint."""

    source = "DOU"

    def _init_session(self) -> bool:
        """GET the main vacancies page to populate the session with the CSRF cookie."""
        logger.info("DOU: GET %s (acquiring CSRF cookie)…", MAIN_URL)
        response = self.get(MAIN_URL)
        if response is None:
            return False
        csrf = self.session.cookies.get("csrftoken", "")
        logger.info(
            "DOU: session ready — csrftoken %s",
            "present" if csrf else "MISSING (will try anyway)",
        )
        return True

    def _fetch_page(self, category: str, count: int) -> list[BeautifulSoup]:
        """POST to the XHR endpoint and return vacancy cards for the given offset.

        The endpoint returns JSON with a single ``html`` key containing an HTML
        fragment — the vacancy list items are NOT the top-level response body.
        """
        csrf = self.session.cookies.get("csrftoken", "")
        logger.debug(
            "DOU [%s]: POST XHR count=%d csrf=%s",
            category,
            count,
            "ok" if csrf else "missing",
        )
        response = self.post(
            f"{XHR_URL}?category={category}",
            data={"csrfmiddlewaretoken": csrf, "count": count},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf,
                "Referer": f"{MAIN_URL}?category={category}",
            },
        )
        if not response:
            logger.warning("DOU [%s]: POST returned None at count=%d", category, count)
            return []
        logger.debug(
            "DOU [%s]: response status=%d length=%d",
            category,
            response.status_code,
            len(response.text),
        )
        if not response.text.strip():
            logger.debug("DOU [%s]: empty response body at count=%d", category, count)
            return []

        try:
            html = response.json().get("html", "")
        except ValueError:
            logger.warning("DOU [%s]: response is not JSON, using raw text", category)
            html = response.text

        if not html.strip():
            logger.info(
                "DOU [%s]: empty html field at count=%d — end of pages", category, count
            )
            return []

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("li.l-vacancy")
        logger.info(
            "DOU [%s]: parsed %d vacancy cards at count=%d", category, len(cards), count
        )
        return cards

    def _fetch_description(self, url: str) -> str:
        """Fetch full job description from individual vacancy page."""
        response = self.get(url)
        if not response:
            return ""
        soup = BeautifulSoup(response.text, "lxml")
        description_div = soup.select_one(".vacancy-section") or soup.select_one(
            ".b-typo.vacancy-text"
        )
        if description_div:
            return description_div.get_text(separator="\n", strip=True)
        return ""

    def _fetch_descriptions_parallel(self, urls: list[str]) -> dict[str, str]:
        """Fetch multiple description pages concurrently via a thread pool.

        requests.Session is thread-safe for concurrent GETs, so we reuse it.
        Returns a dict mapping url → description text.
        """
        results: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=DESCRIPTION_WORKERS) as executor:
            future_to_url = {
                executor.submit(self._fetch_description, url): url for url in urls
            }
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    results[url] = future.result()
                except Exception as e:
                    logger.warning("DOU: description fetch failed for %s: %s", url, e)
                    results[url] = ""
        return results

    def _parse_card(self, card: BeautifulSoup, category: str) -> Optional[RawVacancy]:
        """Extract fields from a single vacancy card."""
        title_tag = card.select_one("a.vt")
        if not title_tag:
            return None

        url = title_tag.get("href", "").split("?")[0]
        if not url:
            return None

        company_tag = card.select_one("a.company")
        salary_tag = card.select_one("span.salary")
        cities_tag = card.select_one("span.cities")
        date_tag = card.select_one("div.date")

        salary_text = salary_tag.get_text(strip=True) if salary_tag else ""
        salary_min, salary_max, salary_currency = _parse_salary(salary_text)

        return RawVacancy(
            url=url,
            source=self.source,
            category=category,
            title=title_tag.get_text(strip=True),
            company=company_tag.get_text(strip=True) if company_tag else "",
            location=cities_tag.get_text(strip=True) if cities_tag else "",
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            published_at=_parse_date(date_tag.get_text(strip=True))
            if date_tag
            else None,
        )

    def scrape(
        self,
        category: str,
        known_urls: frozenset[str] = frozenset(),
        max_pages: int = 0,
    ) -> list[RawVacancy]:
        """Paginate through the XHR endpoint and collect all vacancies for a category.

        Three-phase approach for speed:
          1. Collect all listing cards (fast XHR pages)
          2. Parse cards → split into known (skip) vs new (need description)
          3. Fetch descriptions for new vacancies in parallel

        ``known_urls`` skips the description fetch for already-stored vacancies.
        ``max_pages`` limits pagination (0 = unlimited, useful during development).
        """
        logger.info(
            "DOU [%s]: starting scrape (max_pages=%s)",
            category,
            max_pages or "unlimited",
        )
        if not self._init_session():
            logger.warning("DOU: failed to initialise session for [%s]", category)
            return []

        # ── Phase 1: collect all cards from listing pages ──────────────────
        all_cards: list[BeautifulSoup] = []
        count = 0
        page = 0

        while True:
            cards = self._fetch_page(category, count)
            if not cards:
                break
            all_cards.extend(cards)
            page += 1
            if max_pages and page >= max_pages:
                logger.info(
                    "DOU [%s]: reached max_pages=%d, stopping pagination",
                    category,
                    max_pages,
                )
                break
            count += PAGE_SIZE

        logger.info(
            "DOU [%s]: %d cards on listing pages, parsing…", category, len(all_cards)
        )

        # ── Phase 2: parse cards, separate new vs already-known ────────────
        known_vacancies: list[RawVacancy] = []
        new_vacancies: list[RawVacancy] = []

        for card in all_cards:
            vacancy = self._parse_card(card, category)
            if not vacancy:
                continue
            if vacancy.url in known_urls:
                known_vacancies.append(vacancy)
            else:
                new_vacancies.append(vacancy)

        logger.info(
            "DOU [%s]: %d new, %d already in DB",
            category,
            len(new_vacancies),
            len(known_vacancies),
        )

        # ── Phase 3: fetch descriptions in parallel for new vacancies ──────
        if new_vacancies:
            logger.info(
                "DOU [%s]: fetching %d descriptions in parallel (workers=%d)…",
                category,
                len(new_vacancies),
                DESCRIPTION_WORKERS,
            )
            urls = [v.url for v in new_vacancies]
            descriptions = self._fetch_descriptions_parallel(urls)
            for v in new_vacancies:
                v.description = descriptions.get(v.url, "")
                logger.debug(
                    "DOU [%s]: collected — %s @ %s", category, v.title, v.company
                )

        all_vacancies = known_vacancies + new_vacancies
        logger.info("DOU [%s]: %d vacancies collected", category, len(all_vacancies))
        return all_vacancies
