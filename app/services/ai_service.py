import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from groq import AsyncGroq

from app.config import settings

logger = logging.getLogger(__name__)

_client = AsyncGroq(api_key=settings.groq_api_key, max_retries=1)

# Caps concurrent Groq API calls across all categories.
# Without this, asyncio.gather fires 200+ coroutines that all spin in
# _pick_model(), starving the event loop and triggering cascading 429 retries.
_llm_semaphore = asyncio.Semaphore(4)

# Per-model minimum interval (seconds) between calls, derived from TPM limits.
# Effective RPM = TPM_limit / 1000 tokens_per_request.
# Interval = 60s / effective_RPM, with a small safety margin.
#   llama-4-scout : 30K TPM → 30 eff-RPM → 2.0s
#   llama-3.3-70b : 12K TPM → 12 eff-RPM → 5.5s
#   kimi-k2       : 10K TPM → 10 eff-RPM → 6.5s
#   llama-3.1-8b  :  6K TPM →  6 eff-RPM → 11.0s
_MODEL_INTERVALS: dict[str, float] = {
    "meta-llama/llama-4-scout-17b-16e-instruct": 2.0,
    "llama-3.3-70b-versatile": 5.5,
    "moonshotai/kimi-k2-instruct": 6.5,
    "llama-3.1-8b-instant": 11.0,
}

# Tracks when each model is available next (monotonic seconds).
_model_next_available: dict[str, float] = {m: 0.0 for m in _MODEL_INTERVALS}
_scheduler_lock = asyncio.Lock()


def _penalize_model(model: str, error_str: str) -> None:
    """Push model's next_available far into the future on unrecoverable errors.

    - TPD (tokens per day) exhausted → skip for 24 h
    - 503 over capacity              → skip for 5 min
    - other API errors               → skip for 1 min
    """
    if "tokens per day" in error_str or "per_day" in error_str:
        penalty = 86_400  # 24 hours
        logger.warning("Model %s hit daily token limit — skipping for 24 h", model)
    elif "503" in error_str or "over capacity" in error_str:
        penalty = 300  # 5 minutes
        logger.warning("Model %s is over capacity — skipping for 5 min", model)
    else:
        penalty = 60  # 1 minute
        logger.warning("Model %s returned an error — skipping for 1 min", model)
    _model_next_available[model] = time.monotonic() + penalty


async def _pick_model() -> str:
    """Return the model that becomes available soonest, sleeping if needed."""
    while True:
        async with _scheduler_lock:
            now = time.monotonic()
            model = min(_model_next_available, key=lambda m: _model_next_available[m])
            wait = _model_next_available[model] - now
            if wait <= 0:
                _model_next_available[model] = time.monotonic() + _MODEL_INTERVALS[model]
                return model
        await asyncio.sleep(0.05)


DOU_PROMPT = """Analyze this job vacancy description and return ONLY a JSON object with these fields:
- technologies: list of specific technologies named in the text — programming languages, frameworks, libraries, databases, tools, protocols, and services. Include only items specific enough to be listed as a distinct skill on a developer's CV (e.g. ["Python", "Django", "PostgreSQL"]).
- experience_years: minimum years of experience required as integer, or null if not specified
- english_level: CEFR code — one of: A1, A2, B1, B2, C1, C2 — ONLY if the vacancy explicitly states an English level requirement. Return null if not mentioned.
- responsibilities_summary: 1-2 sentence summary of main job responsibilities in English
- required_skills_summary: 1-2 sentence summary of required skills in English

IMPORTANT: Write ALL text values in English only. Do NOT use Ukrainian or Russian.
Return ONLY valid JSON, no explanation, no markdown.

Vacancy description:
{description}"""

DJINNI_PROMPT = """Analyze this job vacancy description and return ONLY a JSON object with these fields:
- technologies: list of specific technologies named in the text — programming languages, frameworks, libraries, databases, tools, protocols, and services. Include only items specific enough to be listed as a distinct skill on a developer's CV (e.g. ["Python", "FastAPI", "Redis"]).
- responsibilities_summary: 1-2 sentence summary of main job responsibilities in English
- required_skills_summary: 1-2 sentence summary of required skills in English

IMPORTANT: Write ALL text values in English only. Do NOT use Ukrainian or Russian.
Return ONLY valid JSON, no explanation, no markdown.

Vacancy description:
{description}"""


@dataclass
class AIResult:
    """Structured output returned by the LLM for a single vacancy."""

    technologies: list[str]
    experience_years: Optional[int] = None
    english_level: Optional[str] = None
    responsibilities_summary: Optional[str] = None
    required_skills_summary: Optional[str] = None


def _clean_json(text: str) -> str:
    """Extract a JSON object from the model response.

    Handles:
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose around the JSON
    - Finds the outermost { ... } block
    """
    import re
    text = text.strip()
    # Strip code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]).strip()
    # Find the outermost JSON object even if there's surrounding text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return text


_ENGLISH_LEVEL_MAP = {
    "a1": "A1", "beginner": "A1", "elementary": "A1",
    "a2": "A2", "pre-intermediate": "A2",
    "b1": "B1", "intermediate": "B1",
    "b2": "B2", "upper-intermediate": "B2", "upper intermediate": "B2",
    "c1": "C1", "advanced": "C1",
    "c2": "C2", "proficient": "C2", "mastery": "C2", "fluent": "C2",
}


def _normalize_english_level(value: Optional[str]) -> Optional[str]:
    """Normalize english_level to CEFR code (B1, B2, C1 …).

    Handles descriptive words ("Upper-Intermediate" → "B2") and
    the "+" suffix meaning "or higher" ("Upper-Intermediate+" → "B2").
    """
    if not value:
        return None
    key = value.strip().rstrip("+").strip().lower()
    return _ENGLISH_LEVEL_MAP.get(key, value.strip())


async def analyze_vacancy(description: str, source: str) -> Optional[AIResult]:
    """
    Send vacancy description to Groq and parse the structured response.
    Returns None on failure — caller should proceed without AI fields.

    Picks the least-recently-used model via _pick_model() to distribute
    load across all 4 models while respecting per-model TPM rate limits.
    """
    if not description or not settings.groq_api_key:
        return None

    prompt_template = DOU_PROMPT if source == "DOU" else DJINNI_PROMPT
    prompt = prompt_template.format(description=description[:3000])

    try:
        async with _llm_semaphore:
            model = await _pick_model()
            try:
                response = await _client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
            except Exception as e:
                _penalize_model(model, str(e))
                raise
        text = response.choices[0].message.content
        data = json.loads(_clean_json(text))
        return AIResult(
            technologies=[str(t) for t in data.get("technologies", [])],
            experience_years=data.get("experience_years"),
            english_level=_normalize_english_level(data.get("english_level")),
            responsibilities_summary=data.get("responsibilities_summary"),
            required_skills_summary=data.get("required_skills_summary"),
        )
    except (json.JSONDecodeError, AttributeError, KeyError) as e:
        logger.warning("AI parsing failed: %s", e)
        return None
    except Exception as e:
        logger.warning("Groq API error: %s", e)
        return None
