"""calendar_dates.source: источник флагов дня

Значения — CalendarSource (src/dto/calendar_dates_dto.py): 0 — isdayoff.ru, 1 — библиотека holidays.
Существующие строки получают 0: календарь вносился из isdayoff.ru.

Revision ID: ab8c9fdeaeac
Revises: e1a7c3f9b2d4
Create Date: 2026-11-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab8c9fdeaeac'
down_revision: Union[str, None] = 'e1a7c3f9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'calendar_dates',
        sa.Column('source', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('calendar_dates', 'source')
