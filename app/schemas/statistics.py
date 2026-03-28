from pydantic import BaseModel


class CategoryStat(BaseModel):
    category: str
    count: int


class TechnologyStat(BaseModel):
    name: str
    count: int


class SalaryStat(BaseModel):
    category: str
    avg_min: float | None
    avg_max: float | None
    currency: str


class TrendPoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class StackPair(BaseModel):
    tech1: str
    tech2: str
    count: int


class ExperienceBucket(BaseModel):
    level: str  # "No experience", "Junior (1-2)", "Middle (3-4)", "Senior (5+)"
    count: int
