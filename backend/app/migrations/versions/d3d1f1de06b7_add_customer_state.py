"""add customer state

Revision ID: d3d1f1de06b7
Revises: b5873da86606
Create Date: 2026-03-16 18:30:35.819742

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3d1f1de06b7'
down_revision = 'b5873da86606'
branch_labels = None
depends_on = None


customerstate_enum = sa.Enum('none', 'liked', name='customerstate')


def upgrade():
    customerstate_enum.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table('image', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_state', customerstate_enum, server_default='none', nullable=False))


def downgrade():
    with op.batch_alter_table('image', schema=None) as batch_op:
        batch_op.drop_column('customer_state')
    customerstate_enum.drop(op.get_bind(), checkfirst=True)
