"""add activation_token_resent to auditlogtype enum

Revision ID: e069b121109b
Revises: 625bb3257bba
Create Date: 2026-10-23 19:50:29.231552

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e069b121109b'
down_revision = '625bb3257bba'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE auditlogtype ADD VALUE IF NOT EXISTS 'activation_token_resent'")


def downgrade():
    # PostgreSQL does not support removing values from an enum type.
    pass
