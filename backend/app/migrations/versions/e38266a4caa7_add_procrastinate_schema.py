"""add procrastinate schema

Revision ID: e38266a4caa7
Revises: 93dccb13ea4a
Create Date: 2026-10-26 10:00:00.000000

"""

import os
import sys

# procrastinate_schema.py sits next to versions/, which is not a package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import op  # noqa: E402
import procrastinate_schema  # noqa: E402

# revision identifiers, used by Alembic.
revision = "e38266a4caa7"
down_revision = "93dccb13ea4a"
branch_labels = None
depends_on = None

# Highest migration shipped by procrastinate 3.10.0 (the pinned version).
PROCRASTINATE_VERSION = "03.04.00"


def upgrade():
    procrastinate_schema.ensure_schema(op.get_bind(), PROCRASTINATE_VERSION)


def downgrade():
    # Baseline revision: removes the whole queue, including pending jobs.
    procrastinate_schema.drop_schema(op.get_bind())
