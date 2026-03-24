"""add ticket_comment_added notification type

Revision ID: c7f3a92e1d05
Revises: 5eda2290da8c
Create Date: 2026-03-24 21:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c7f3a92e1d05'
down_revision = '5eda2290da8c'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE notificationtype ADD VALUE 'ticket_comment_added'")


def downgrade():
    # PostgreSQL does not support removing enum values without recreating the type.
    pass
