"""initial

Revision ID: 001
Revises:
Create Date: 2026-03-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vacancies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("url", sa.Text, unique=True, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("company", sa.Text),
        sa.Column("location", sa.Text),
        sa.Column("salary_min", sa.Integer, nullable=True),
        sa.Column("salary_max", sa.Integer, nullable=True),
        sa.Column("salary_currency", sa.String(10), nullable=True),
        sa.Column("description", sa.Text),
        sa.Column("experience_years", sa.Integer, nullable=True),
        sa.Column("english_level", sa.String(50), nullable=True),
        sa.Column("responsibilities_summary", sa.Text, nullable=True),
        sa.Column("required_skills_summary", sa.Text, nullable=True),
        sa.Column("scraped_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
    )
    op.create_table(
        "technologies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
    )
    op.create_table(
        "vacancy_technologies",
        sa.Column("vacancy_id", sa.Integer, sa.ForeignKey("vacancies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("technology_id", sa.Integer, sa.ForeignKey("technologies.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_vacancies_source", "vacancies", ["source"])
    op.create_index("ix_vacancies_category", "vacancies", ["category"])
    op.create_index("ix_vacancies_scraped_at", "vacancies", ["scraped_at"])


def downgrade() -> None:
    op.drop_table("vacancy_technologies")
    op.drop_table("technologies")
    op.drop_table("vacancies")
