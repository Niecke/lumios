"""add subscriptions

Revision ID: 21f317e04fe5
Revises: c7f3a92e1d05
Create Date: 2026-03-25 19:23:42.846555

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '21f317e04fe5'
down_revision = 'c7f3a92e1d05'
branch_labels = None
depends_on = None


def upgrade():
    subscription_enum = sa.Enum('free', 'standard', 'premium', name='subscriptiontype')
    subscription_enum.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subscription', subscription_enum, server_default='free', nullable=False))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('subscription')

    sa.Enum(name='subscriptiontype').drop(op.get_bind(), checkfirst=True)
