"""Add admin_level to users and create approval log tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-26

This migration:
1. Adds admin_level column to users table
2. Creates admin_permission_logs table for audit
3. Creates approval_logs table for tracking approval workflow
4. Migrates existing is_admin=True users to admin_level='university'
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # 1) Add admin_level column to users table
    op.add_column('users', sa.Column('admin_level', sa.String(20), nullable=True, default='none'))

    # 2) Create index for admin_level
    op.create_index('idx_users_admin_level', 'users', ['admin_level'])

    # 3) Create admin_permission_logs table
    op.create_table(
        'admin_permission_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),  # 'grant', 'revoke', 'change'
        sa.Column('old_level', sa.String(20), nullable=True),
        sa.Column('new_level', sa.String(20), nullable=True),
        sa.Column('performed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('performed_at', sa.DateTime(), default=datetime.utcnow),
        sa.Column('notes', sa.Text(), nullable=True),
    )
    op.create_index('idx_admin_log_user', 'admin_permission_logs', ['user_id'])
    op.create_index('idx_admin_log_performer', 'admin_permission_logs', ['performed_by'])
    op.create_index('idx_admin_log_time', 'admin_permission_logs', ['performed_at'])

    # 4) Create approval_logs table
    op.create_table(
        'approval_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_type', sa.String(50), nullable=False),  # 'publication', 'project', 'activity'
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(30), nullable=False),  # 'department_approve', 'faculty_approve', etc.
        sa.Column('old_status', sa.String(30), nullable=True),
        sa.Column('new_status', sa.String(30), nullable=True),
        sa.Column('performed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('performed_at', sa.DateTime(), default=datetime.utcnow),
        sa.Column('notes', sa.Text(), nullable=True),
    )
    op.create_index('idx_approval_log_item', 'approval_logs', ['item_type', 'item_id'])
    op.create_index('idx_approval_log_performer', 'approval_logs', ['performed_by'])

    # 5) Migrate existing admin users
    # Set admin_level = 'university' for users with is_admin = True (if column exists)
    # Set admin_level = 'none' for other users
    connection = op.get_bind()

    # Check if is_admin column exists
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('users')]

    if 'is_admin' in columns:
        # Migrate existing admins to university level
        connection.execute(
            sa.text("UPDATE users SET admin_level = 'university' WHERE is_admin = TRUE OR is_admin = 1")
        )
        connection.execute(
            sa.text("UPDATE users SET admin_level = 'none' WHERE admin_level IS NULL OR admin_level = ''")
        )
    else:
        # No is_admin column, set all to 'none'
        connection.execute(
            sa.text("UPDATE users SET admin_level = 'none' WHERE admin_level IS NULL")
        )


def downgrade():
    # 1) Drop approval_logs table
    op.drop_index('idx_approval_log_performer', 'approval_logs')
    op.drop_index('idx_approval_log_item', 'approval_logs')
    op.drop_table('approval_logs')

    # 2) Drop admin_permission_logs table
    op.drop_index('idx_admin_log_time', 'admin_permission_logs')
    op.drop_index('idx_admin_log_performer', 'admin_permission_logs')
    op.drop_index('idx_admin_log_user', 'admin_permission_logs')
    op.drop_table('admin_permission_logs')

    # 3) Drop admin_level column and index
    op.drop_index('idx_users_admin_level', 'users')
    op.drop_column('users', 'admin_level')
