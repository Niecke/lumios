"""add gdpr_export to auditlogtype enum

Revision ID: a1b2c3d4e5f6
Revises: 350f82113813
Create Date: 2026-03-29 00:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "350f82113813"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE auditlogtype ADD VALUE 'gdpr_export'")


def downgrade():
    # PostgreSQL does not support removing values from an enum type.
    pass
