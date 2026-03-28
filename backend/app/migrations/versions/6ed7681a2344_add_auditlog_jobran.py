"""add auditlog+jobran

Revision ID: 6ed7681a2344
Revises: d4e5f6a7b8c9
Create Date: 2026-03-28 13:53:38.492951

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6ed7681a2344'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('job_run',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_name', sa.String(length=100), nullable=False),
    sa.Column('ran_at', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('records_affected', sa.Integer(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('job_run', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_run_job_name'), ['job_name'], unique=False)

    op.create_table('audit_log',
    sa.Column('id', sa.LargeBinary(length=16), nullable=False),
    sa.Column('audit_type', sa.Enum('user_created', 'user_activated', 'user_deactivated', 'user_reactivated', 'user_deleted', 'password_changed', 'password_set_by_admin', 'login_backend', 'login_frontend', 'login_failed', 'library_created', 'library_edited', 'library_deleted', 'library_finished', 'picture_uploaded', 'picture_deleted', 'picture_downloaded', name='auditlogtype'), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('audit_date', sa.DateTime(), nullable=False),
    sa.Column('creator_id', sa.Integer(), nullable=True),
    sa.Column('related_object_type', sa.String(length=16), nullable=True),
    sa.Column('related_object_id', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['creator_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_audit_date'), ['audit_date'], unique=False)


def downgrade():
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_audit_date'))

    op.drop_table('audit_log')
    with op.batch_alter_table('job_run', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_run_job_name'))

    op.drop_table('job_run')
