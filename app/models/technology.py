from typing import TYPE_CHECKING, Annotated

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.vacancy import intpk, vacancy_technologies

if TYPE_CHECKING:
    from app.models.vacancy import Vacancy

unique_str100 = Annotated[str, mapped_column(String(100), unique=True)]


class Technology(Base):
    """Normalised technology / tool name used across multiple vacancies."""

    __tablename__ = "technologies"

    id: Mapped[intpk]
    name: Mapped[unique_str100]

    vacancies: Mapped[list["Vacancy"]] = relationship(
        secondary=vacancy_technologies, back_populates="technologies"
    )
