"""add promo_groups table and users.promo_group_id

Revision ID: c4d8a1f23e77
Revises: a1c3e5f79b02
Create Date: 2026-08-18 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d8a1f23e77'
down_revision = 'a1c3e5f79b02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'promo_groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('discount_percent', sa.Integer(), nullable=False, server_default='0'),
    )
    # batch_alter_table — SQLite не умеет ALTER TABLE ADD CONSTRAINT напрямую,
    # Alembic пересоздаёт таблицу под капотом; на Postgres работает как обычный ALTER.
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('promo_group_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_users_promo_group_id', 'promo_groups', ['promo_group_id'], ['id'], ondelete='SET NULL'
        )


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_constraint('fk_users_promo_group_id', type_='foreignkey')
        batch_op.drop_column('promo_group_id')
    op.drop_table('promo_groups')
