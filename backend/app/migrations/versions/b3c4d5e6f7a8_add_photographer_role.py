"""add photographer role

Revision ID: b3c4d5e6f7a8
Revises: 482fc9a1a659
Create Date: 2026-03-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "482fc9a1a659"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO role (name, description) VALUES ('photographer', 'Photographer portal access')"
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM role WHERE name = 'photographer'"))
