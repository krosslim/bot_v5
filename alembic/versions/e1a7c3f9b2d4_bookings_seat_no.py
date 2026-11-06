"""bookings.seat_no: номер места в брони

Схема зала (подписи, столы, место руководителя) живёт в коде: src/ui/widgets/layout.py.
В базе хранится только номер места.

Revision ID: e1a7c3f9b2d4
Revises: d07a40290d64
Create Date: 2026-11-06 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a7c3f9b2d4'
down_revision: Union[str, None] = 'd07a40290d64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Сколько мест у команды на момент миграции (OFFICE_LAYOUT). Брони сверх этого числа останутся без места
SEATS_COUNT = 10


def upgrade() -> None:
    op.add_column('bookings', sa.Column('seat_no', sa.SmallInteger(), nullable=True))
    op.create_check_constraint('ck_bookings_seat_no_positive', 'bookings', 'seat_no > 0')
    op.create_index(
        'ux_bookings_date_seat_booked',
        'bookings',
        ['cal_date', 'seat_no'],
        unique=True,
        postgresql_where=sa.text("status = 'BOOKED'"),
    )
    op.add_column('booking_events', sa.Column('seat_no', sa.SmallInteger(), nullable=True))

    # Будущим активным броням раздаём места по порядку записи
    op.execute(
        f"""
        UPDATE bookings b
           SET seat_no = x.rn
          FROM (
                SELECT booking_id,
                       row_number() OVER (PARTITION BY cal_date ORDER BY created_at, booking_id) AS rn
                  FROM bookings
                 WHERE status = 'BOOKED'
                   AND cal_date >= (now() AT TIME ZONE 'Europe/Moscow')::date
               ) x
         WHERE b.booking_id = x.booking_id
           AND x.rn <= {SEATS_COUNT}
        """
    )


def downgrade() -> None:
    op.drop_column('booking_events', 'seat_no')
    op.drop_index('ux_bookings_date_seat_booked', table_name='bookings')
    op.drop_constraint('ck_bookings_seat_no_positive', 'bookings', type_='check')
    op.drop_column('bookings', 'seat_no')
