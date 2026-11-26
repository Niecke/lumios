"""update procrastinate schema to 03.12.00

Revision ID: 6f7e598ea004
Revises: 909865599f3b
Create Date: 2026-11-26 09:55:42.156143

"""

import os
import sys

# procrastinate_schema.py sits next to versions/, which is not a package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import op  # noqa: E402
import procrastinate_schema  # noqa: E402

# revision identifiers, used by Alembic.
revision = "6f7e598ea004"
down_revision = "909865599f3b"
branch_labels = None
depends_on = None

# Highest migration shipped by procrastinate 3.12.0 (pinned at the time of this revision).
PROCRASTINATE_VERSION = "03.12.00"


def upgrade():
    procrastinate_schema.ensure_schema(op.get_bind(), PROCRASTINATE_VERSION)


def downgrade():
    # Procrastinate ships no down migrations: the queue keeps the 03.12.00 schema
    # and the recorded version. The baseline revision's downgrade drops it all.
    pass
