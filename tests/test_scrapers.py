"""Unit tests for scrapers using mocked HTTP responses."""
import json

import pytest
import responses as resp_mock

from app.scrapers.dou import DouScraper, _parse_salary, _parse_date
from app.scrapers.djinni import DjinniScraper, _parse_experience_years


# ── _parse_salary ──────────────────────────────────────────────────────────────

def test_parse_salary_range_usd():
    mn, mx, cur = _parse_salary("$2000–3750")
    assert mn == 2000
    assert mx == 3750
    assert cur == "USD"


def test_parse_salary_single_usd():
    mn, mx, cur = _parse_salary("$1500")
    assert mn == 1500
    assert mx == 1500
    assert cur == "USD"


def test_parse_salary_empty():
    mn, mx, cur = _parse_salary("")
    assert mn is None
    assert mx is None
    assert cur is None


# ── _parse_date ────────────────────────────────────────────────────────────────

def test_parse_date_valid():
    dt = _parse_date("5 березня")
    assert dt is not None
    assert dt.day == 5
    assert dt.month == 3


def test_parse_date_invalid():
    assert _parse_date("invalid") is None
    assert _parse_date("") is None


# ── _parse_experience_years ────────────────────────────────────────────────────

def test_experience_years_parse():
    assert _parse_experience_years("3 роки") == 3
    assert _parse_experience_years("1 рік") is None  # "рік" not "рок"
    assert _parse_experience_years("6 місяців") is None
    assert _parse_experience_years("") is None


# ── DOU XHR scraper (mocked HTTP) ─────────────────────────────────────────────

DOU_XHR_HTML = """
<ul class="lt">
  <li class="l-vacancy">
    <div class="date">5 березня</div>
    <div class="title">
      <a class="vt" href="https://jobs.dou.ua/companies/test/vacancies/123/">Senior Python Dev</a>
      <a class="company">TestCorp</a>
      <span class="salary">$3000–4000</span>
      <span class="cities">віддалено</span>
    </div>
  </li>
</ul>
"""

DOU_DETAIL_HTML = """
<div class="vacancy-section">
  <p>We are looking for a Python developer.</p>
  <ul><li>5+ years Python</li><li>Django expertise</li></ul>
</div>
"""


@resp_mock.activate
def test_dou_scraper_parses_card():
    # Session init: GET main page to receive CSRF cookie
    resp_mock.add(resp_mock.GET, "https://jobs.dou.ua/vacancies/", body="<html></html>", status=200)
    # First XHR POST returns JSON {"html": "<vacancy cards>"} — mirrors real DOU response
    resp_mock.add(resp_mock.POST, "https://jobs.dou.ua/vacancies/xhr-load/",
                  body=json.dumps({"html": DOU_XHR_HTML}), content_type="application/json", status=200)
    # Individual vacancy page for description
    resp_mock.add(resp_mock.GET, "https://jobs.dou.ua/companies/test/vacancies/123/", body=DOU_DETAIL_HTML, status=200)
    # Second XHR POST returns empty html → stop pagination
    resp_mock.add(resp_mock.POST, "https://jobs.dou.ua/vacancies/xhr-load/",
                  body=json.dumps({"html": ""}), content_type="application/json", status=200)

    scraper = DouScraper()
    results = scraper.scrape("Python")

    assert len(results) == 1
    v = results[0]
    assert v.title == "Senior Python Dev"
    assert v.company == "TestCorp"
    assert v.salary_min == 3000
    assert v.salary_max == 4000
    assert v.salary_currency == "USD"
    assert v.location == "віддалено"
    assert "Python developer" in v.description


# ── Djinni JSON-LD scraper (mocked HTTP) ──────────────────────────────────────

DJINNI_HTML = """
<html><head>
<script type="application/ld+json">
[{
  "@type": "JobPosting",
  "title": "Python Backend Engineer",
  "url": "https://djinni.co/jobs/999-python-backend/",
  "description": "<p>Build scalable APIs with FastAPI.</p>",
  "baseSalary": {"value": {"minValue": 2500, "maxValue": 4000, "currency": "USD"}},
  "hiringOrganization": {"name": "AwesomeCorp"},
  "jobLocation": {"address": {"addressLocality": "Київ"}},
  "experienceRequirements": "3 роки",
  "datePosted": "2026-03-01"
}]
</script>
</head><body></body></html>
"""


@resp_mock.activate
def test_djinni_scraper_parses_json_ld():
    resp_mock.add(resp_mock.GET, "https://djinni.co/jobs/", body=DJINNI_HTML, status=200)
    resp_mock.add(resp_mock.GET, "https://djinni.co/jobs/", body="<html><body></body></html>", status=200)

    scraper = DjinniScraper()
    results = scraper.scrape("python")

    assert len(results) == 1
    v = results[0]
    assert v.title == "Python Backend Engineer"
    assert v.company == "AwesomeCorp"
    assert v.salary_min == 2500
    assert v.salary_max == 4000
    assert v.salary_currency == "USD"
    assert v.location == "Київ"
    assert v.experience_years == 3
    assert "FastAPI" in v.description
