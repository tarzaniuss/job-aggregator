import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from app.config import settings
from app.scrapers.base import BaseScraper, RawVacancy

logger = logging.getLogger(__name__)

BASE_URL = "https://djinni.co"
JOBS_URL = f"{BASE_URL}/jobs/"

KEYWORD_TO_CATEGORY = settings.djinni_keywords


def _parse_experience_years(text: str) -> Optional[int]:
    """Parse '3 роки' → 3, '6 місяців' → None (less than a year)."""
    if not text:
        return None
    match = re.search(r"(\d+)\s*рок", text)
    if match:
        return int(match.group(1))
    return None


def _parse_salary_range(
    salary_data: dict,
) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Parse JSON-LD baseSalary object."""
    try:
        value = salary_data.get("value", {})
        currency = value.get("currency")
        min_val = value.get("minValue")
        max_val = value.get("maxValue")
        single = value.get("value")

        salary_min = int(min_val) if min_val else (int(single) if single else None)
        salary_max = int(max_val) if max_val else salary_min
        return salary_min, salary_max, currency
    except (TypeError, ValueError):
        return None, None, None


def _extract_english_level(soup: BeautifulSoup) -> Optional[str]:
    """Find English level from job card metadata row.

    Djinni renders it as <span class="text-nowrap">Англійська - B2</span>
    in the card's info bar, so we scan all text-nowrap spans for a level code.
    """
    for span in soup.select("span.text-nowrap"):
        text = span.get_text(strip=True)
        match = re.search(r"-\s*([A-C]\d)\b", text)
        if match:
            return match.group(1)  # e.g. "B2"
    return None


def _extract_location(soup: BeautifulSoup) -> Optional[str]:
    """Extract location from the card's <span class='location-text'>.

    Djinni wraps single-city jobs as "Україна(Київ)" — we strip the country
    prefix and keep only the content inside the parentheses.
    Returns None if absent (fully remote jobs often have no location element).
    """
    el = soup.select_one("span.location-text")
    if not el:
        return None
    text = el.get_text(strip=True)
    if not text:
        return None
    # "Країна(міста)" → "міста"
    match = re.match(r"^[^(]+\((.+)\)$", text)
    if match:
        text = match.group(1)
    return text or None


def _parse_json_ld(soup: BeautifulSoup) -> list[dict]:
    """Extract all JSON-LD JobPosting objects from a page."""
    result = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                result.extend(d for d in data if d.get("@type") == "JobPosting")
            elif isinstance(data, dict) and data.get("@type") == "JobPosting":
                result.append(data)
        except (json.JSONDecodeError, AttributeError):
            continue
    return result


class DjinniScraper(BaseScraper):
    """Scraper for Djinni.co that extracts structured data from JSON-LD blocks."""

    source = "Djinni"

    def _fetch_page(
        self, keyword: str, page: int
    ) -> tuple[list[dict], list[BeautifulSoup]]:
        """
        Returns (json_ld_items, card_soups) for a single listing page.
        card_soups are used to extract english_level not present in JSON-LD.
        """
        params = {"primary_keyword": keyword, "page": page}
        response = self.get(JOBS_URL, params=params)
        if not response:
            return [], []

        soup = BeautifulSoup(response.text, "lxml")
        json_ld = _parse_json_ld(soup)

        cards = soup.select("div.job-item")
        return json_ld, cards

    def _build_vacancy(
        self, ld: dict, category: str, card_soup: Optional[BeautifulSoup] = None
    ) -> Optional[RawVacancy]:
        """Build RawVacancy from a JSON-LD dict."""
        url = ld.get("url") or ld.get("@id", "")
        if not url:
            return None
        if url.startswith("/"):
            url = BASE_URL + url

        title = ld.get("title", "")
        description = BeautifulSoup(ld.get("description", ""), "lxml").get_text(
            separator="\n", strip=True
        )

        org = ld.get("hiringOrganization", {})
        company = org.get("name", "") if isinstance(org, dict) else ""

        # Location: TELECOMMUTE flag takes priority → "Віддалено".
        # Otherwise read city from the card's <span class="location-text">.
        # Fall back to JSON-LD addressLocality if card HTML is unavailable.
        if ld.get("jobLocationType") == "TELECOMMUTE":
            location = "віддалено"
        else:
            location = _extract_location(card_soup) if card_soup else None
            if not location:
                location_data = ld.get("jobLocation", {})
                if isinstance(location_data, list):
                    location_data = location_data[0] if location_data else {}
                address = (
                    location_data.get("address", {})
                    if isinstance(location_data, dict)
                    else {}
                )
                locality = (
                    address.get("addressLocality", "")
                    if isinstance(address, dict)
                    else ""
                )
                if isinstance(locality, list):
                    locality = ", ".join(locality)
                location = locality or None

        salary_data = ld.get("baseSalary")
        if salary_data:
            salary_min, salary_max, salary_currency = _parse_salary_range(salary_data)
        else:
            salary_min = salary_max = salary_currency = None

        experience_req = ld.get("experienceRequirements", "")
        if isinstance(experience_req, dict):
            # JSON-LD gives numeric months: {"monthsOfExperience": 12.0}
            months = experience_req.get("monthsOfExperience")
            experience_years = (
                int(months) // 12 if months and int(months) >= 12 else None
            )
        else:
            # Fallback: plain text like "3 роки"
            experience_years = _parse_experience_years(str(experience_req))

        date_posted = ld.get("datePosted")
        published_at = None
        if date_posted:
            try:
                published_at = datetime.fromisoformat(date_posted)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        english_level = _extract_english_level(card_soup) if card_soup else None

        return RawVacancy(
            url=url,
            source=self.source,
            category=category,
            title=title,
            company=company,
            location=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            description=description,
            experience_years=experience_years,
            english_level=english_level,
            published_at=published_at,
        )

    def scrape(self, keyword: str, max_pages: int = 0) -> list[RawVacancy]:
        """Paginate through job listings for a keyword and return all vacancies.

        ``max_pages`` limits pagination (0 = unlimited, useful during development).
        """
        category = KEYWORD_TO_CATEGORY.get(keyword, keyword)
        logger.info(
            "Djinni [%s]: starting scrape (max_pages=%s)",
            keyword,
            max_pages or "unlimited",
        )
        vacancies: list[RawVacancy] = []
        page = 1

        while True:
            logger.debug("Djinni [%s]: fetching page %d", keyword, page)
            json_ld_items, cards = self._fetch_page(keyword, page)
            if not json_ld_items:
                logger.info("Djinni [%s]: no items on page %d — done", keyword, page)
                break

            logger.info(
                "Djinni [%s]: got %d items on page %d",
                keyword,
                len(json_ld_items),
                page,
            )
            for i, ld in enumerate(json_ld_items):
                card_soup = cards[i] if i < len(cards) else None
                vacancy = self._build_vacancy(ld, category, card_soup)
                if not vacancy:
                    continue
                vacancies.append(vacancy)
                logger.info(
                    "Djinni [%s]: collected — %s @ %s",
                    keyword,
                    vacancy.title,
                    vacancy.company,
                )

            if max_pages and page >= max_pages:
                logger.info(
                    "Djinni [%s]: reached max_pages=%d, stopping", keyword, max_pages
                )
                break

            page += 1

        logger.info("Djinni [%s]: %d vacancies collected", keyword, len(vacancies))
        return vacancies
