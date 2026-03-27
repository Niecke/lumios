"""add library_viewed to notificationtype enum

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-27 00:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE notificationtype ADD VALUE 'library_viewed'")


def downgrade():
    # PostgreSQL does not support removing values from an enum type.
    # To roll back, the column and all rows using the value would need
    # to be migrated first — left as a no-op here.
    pass
