"""add master_dfd progress and email fields

Revision ID: d7e8f9g0h1i2
Revises: c5d6e7f8g9h0
Create Date: 2026-03-23 20:09:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd7e8f9g0h1i2'
down_revision = 'c5d6e7f8g9h0'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    """Add current_stage, progress_percent, and notification_email to master_dfds."""
    if _table_exists('master_dfds'):
        if not _column_exists('master_dfds', 'current_stage'):
            op.add_column('master_dfds', sa.Column('current_stage', sa.String(), nullable=True))
            print("✅ Added current_stage column to master_dfds")
        else:
            print("⚠️  current_stage column already exists in master_dfds")
        
        if not _column_exists('master_dfds', 'progress_percent'):
            op.add_column('master_dfds', sa.Column('progress_percent', sa.Float(), nullable=True))
            print("✅ Added progress_percent column to master_dfds")
        else:
            print("⚠️  progress_percent column already exists in master_dfds")
        
        if not _column_exists('master_dfds', 'notification_email'):
            op.add_column('master_dfds', sa.Column('notification_email', sa.String(), nullable=True))
            print("✅ Added notification_email column to master_dfds")
        else:
            print("⚠️  notification_email column already exists in master_dfds")
    else:
        print("⚠️  master_dfds table does not exist, skipping")


def downgrade():
    """Remove current_stage, progress_percent, and notification_email from master_dfds."""
    if _table_exists('master_dfds'):
        if _column_exists('master_dfds', 'notification_email'):
            op.drop_column('master_dfds', 'notification_email')
            print("✅ Dropped notification_email column from master_dfds")
        
        if _column_exists('master_dfds', 'progress_percent'):
            op.drop_column('master_dfds', 'progress_percent')
            print("✅ Dropped progress_percent column from master_dfds")
        
        if _column_exists('master_dfds', 'current_stage'):
            op.drop_column('master_dfds', 'current_stage')
            print("✅ Dropped current_stage column from master_dfds")
    else:
        print("⚠️  master_dfds table does not exist, skipping")
