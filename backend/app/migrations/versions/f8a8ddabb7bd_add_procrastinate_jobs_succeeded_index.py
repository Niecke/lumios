"""add procrastinate jobs succeeded index

Revision ID: f8a8ddabb7bd
Revises: e13eba907ad1
Create Date: 2026-11-02 15:35:52.263088

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8a8ddabb7bd'
down_revision = 'e13eba907ad1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "idx_procrastinate_jobs_succeeded",
        "procrastinate_jobs",
        [sa.text("id DESC"), "queue_name", "task_name"],
        postgresql_where=sa.text("status = 'succeeded'"),
    )


def downgrade():
    op.drop_index("idx_procrastinate_jobs_succeeded", table_name="procrastinate_jobs")
