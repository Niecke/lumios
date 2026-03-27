"""add download_enabled to library

Revision ID: b2c3d4e5f6a7
Revises: 0c612f250d48
Create Date: 2026-03-27 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "0c612f250d48"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("library", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "download_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("library", schema=None) as batch_op:
        batch_op.drop_column("download_enabled")
