from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.technology import Technology

intpk = Annotated[int, mapped_column(primary_key=True)]
opt_text = Annotated[str | None, mapped_column(Text)]
opt_int = Annotated[int | None, mapped_column(Integer)]
opt_str10 = Annotated[str | None, mapped_column(String(10))]
opt_str50 = Annotated[str | None, mapped_column(String(50))]

vacancy_technologies = Table(
    "vacancy_technologies",
    Base.metadata,
    Column(
        "vacancy_id",
        Integer,
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "technology_id",
        Integer,
        ForeignKey("technologies.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Vacancy(Base):
    """Job vacancy scraped from an external source and enriched by AI."""

    __tablename__ = "vacancies"

    id: Mapped[intpk]
    url: Mapped[str] = mapped_column(Text, unique=True)
    source: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(50))
    title: Mapped[opt_text]
    company: Mapped[opt_text]
    location: Mapped[opt_text]
    salary_min: Mapped[opt_int]
    salary_max: Mapped[opt_int]
    salary_currency: Mapped[opt_str10]
    description: Mapped[opt_text]
    experience_years: Mapped[opt_int]
    english_level: Mapped[opt_str50]
    responsibilities_summary: Mapped[opt_text]
    required_skills_summary: Mapped[opt_text]
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    technologies: Mapped[list["Technology"]] = relationship(
        secondary=vacancy_technologies, back_populates="vacancies"
    )
