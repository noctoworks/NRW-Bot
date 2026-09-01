"""add support_tickets and support_message_deliveries, ticket_id on support_messages

Revision ID: dba0f1887958
Revises: 7d7b387bd40d
Create Date: 2026-08-28 00:00:00.000000

Редизайн поддержки (см. диалог 2026-08-28): раньше "тред" был неявной
группировкой support_messages по user_id, без статуса и без multi-admin
роутинга (admin_message_id хранился только для первого админа из
ADMIN_TELEGRAM_IDS — реплай остальных админов никуда не долетал, см.
app/handlers/support.py). Теперь — явный SupportTicket (open/closed,
assigned_admin) + SupportMessageDelivery (по одной строке на каждого админа,
кому переслано конкретное сообщение), чтобы ответить мог любой админ.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dba0f1887958'
down_revision = '7d7b387bd40d'
branch_labels = None
depends_on = None


support_messages = sa.table(
    'support_messages',
    sa.column('id', sa.Integer),
    sa.column('user_id', sa.Integer),
    sa.column('direction', sa.String),
    sa.column('ticket_id', sa.Integer),
    sa.column('admin_message_id', sa.BigInteger),
)

support_tickets = sa.table(
    'support_tickets',
    sa.column('id', sa.Integer),
    sa.column('user_id', sa.Integer),
    sa.column('status', sa.String),
)

support_message_deliveries = sa.table(
    'support_message_deliveries',
    sa.column('support_message_id', sa.Integer),
    sa.column('admin_telegram_id', sa.BigInteger),
    sa.column('admin_message_id', sa.BigInteger),
)


def upgrade() -> None:
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('assigned_admin_id', sa.Integer(), nullable=True),
        sa.Column('assigned_admin_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_admin_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_support_tickets_user_id', 'support_tickets', ['user_id'])

    op.create_table(
        'support_message_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('support_message_id', sa.Integer(), nullable=False),
        sa.Column('admin_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('admin_message_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['support_message_id'], ['support_messages.id'], ondelete='CASCADE'),
    )
    op.create_index(
        'ix_support_message_deliveries_support_message_id',
        'support_message_deliveries',
        ['support_message_id'],
    )

    # Добавляем ticket_id без FK/NOT NULL — сначала бэкофилим данные, ограничения
    # накладываем позже одним batch_alter_table (см. паттерн c4d8a1f23e77_add_promo_groups.py).
    op.add_column('support_messages', sa.Column('ticket_id', sa.Integer(), nullable=True))

    connection = op.get_bind()

    # Один тикет на каждый user_id, у которого уже есть сообщения. Статус — по
    # той же эвристике, что уже жила как "unread" в admin_routes.py: если
    # последнее сообщение юзера direction='in' (не отвечено) — тикет open,
    # иначе (последним отвечал админ) — closed.
    distinct_users = connection.execute(
        sa.select(support_messages.c.user_id).distinct()
    ).scalars().all()
    for user_id in distinct_users:
        last_direction = connection.execute(
            sa.select(support_messages.c.direction)
            .where(support_messages.c.user_id == user_id)
            .order_by(support_messages.c.id.desc())
            .limit(1)
        ).scalar_one()
        ticket_id = connection.execute(
            support_tickets.insert()
            .values(user_id=user_id, status='open' if last_direction == 'in' else 'closed')
            .returning(support_tickets.c.id)
        ).scalar_one()
        connection.execute(
            support_messages.update()
            .where(support_messages.c.user_id == user_id)
            .values(ticket_id=ticket_id)
        )

    # Исторический admin_message_id указывал на копию, отправленную первому
    # админу из sorted(ADMIN_TELEGRAM_IDS) (см. докстринг app/handlers/support.py) —
    # переносим 1-в-1 в новую таблицу доставок. Корректно, если состав
    # ADMIN_TELEGRAM_IDS не менялся с момента этих сообщений (проверить перед
    # прогоном на проде, если там есть открытые непроверенные тикеты).
    from app.config import settings

    admin_ids = settings.admin_ids()
    if admin_ids:
        first_admin_id = min(admin_ids)
        rows = connection.execute(
            sa.select(support_messages.c.id, support_messages.c.admin_message_id).where(
                support_messages.c.admin_message_id.is_not(None)
            )
        ).all()
        for message_id, admin_message_id in rows:
            connection.execute(
                support_message_deliveries.insert().values(
                    support_message_id=message_id,
                    admin_telegram_id=first_admin_id,
                    admin_message_id=admin_message_id,
                )
            )

    with op.batch_alter_table('support_messages') as batch_op:
        batch_op.alter_column('ticket_id', nullable=False)
        batch_op.create_foreign_key(
            'fk_support_messages_ticket_id', 'support_tickets', ['ticket_id'], ['id'], ondelete='CASCADE'
        )
        batch_op.drop_column('admin_message_id')
    op.create_index('ix_support_messages_ticket_id', 'support_messages', ['ticket_id'])


def downgrade() -> None:
    connection = op.get_bind()

    with op.batch_alter_table('support_messages') as batch_op:
        batch_op.add_column(sa.Column('admin_message_id', sa.BigInteger(), nullable=True))

    # Данные восстанавливаем не 1-в-1 (после multi-admin роутинга это уже
    # неоднозначно) — берём произвольную доставку на сообщение, только чтобы
    # старая колонка не была пустой при откате.
    rows = connection.execute(
        sa.select(
            support_message_deliveries.c.support_message_id,
            support_message_deliveries.c.admin_message_id,
        )
    ).all()
    for message_id, admin_message_id in rows:
        connection.execute(
            support_messages.update()
            .where(support_messages.c.id == message_id)
            .values(admin_message_id=admin_message_id)
        )

    op.drop_index('ix_support_messages_ticket_id', table_name='support_messages')
    with op.batch_alter_table('support_messages') as batch_op:
        batch_op.drop_constraint('fk_support_messages_ticket_id', type_='foreignkey')
        batch_op.drop_column('ticket_id')

    op.drop_index('ix_support_message_deliveries_support_message_id', table_name='support_message_deliveries')
    op.drop_table('support_message_deliveries')
    op.drop_index('ix_support_tickets_user_id', table_name='support_tickets')
    op.drop_table('support_tickets')
