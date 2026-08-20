"""add full_name to users

Revision ID: a3b6e0f2c8d4
Revises: f7a2c9d4e1b6
Create Date: 2026-08-18 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3b6e0f2c8d4'
down_revision = 'f7a2c9d4e1b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('full_name', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'full_name')
