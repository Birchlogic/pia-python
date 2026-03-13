"""add_pipeline_stage_logs_and_progress_tracking

Revision ID: b1c2d3e4f5a6
Revises: f9f99574490c
Create Date: 2026-03-13 17:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'f9f99574490c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Add pipeline_stage_logs table and progress tracking columns to dfd_sessions."""

    # 1. Create pipeline_stage_logs table
    if not _table_exists('pipeline_stage_logs'):
        op.create_table('pipeline_stage_logs',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('session_id', sa.String(), nullable=False),
            sa.Column('stage', sa.String(), nullable=False),
            sa.Column('stage_order', sa.Integer(), nullable=False),
            sa.Column('output', sa.JSON(), nullable=True),
            sa.Column('api_key_hash', sa.String(), nullable=True),
            sa.Column('in_tokens', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('out_tokens', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('duration_ms', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_pipeline_stage_logs_session_id', 'pipeline_stage_logs', ['session_id'])

    # 2. Add progress tracking columns to dfd_sessions
    if _table_exists('dfd_sessions'):
        if not _column_exists('dfd_sessions', 'current_stage'):
            op.add_column('dfd_sessions', sa.Column('current_stage', sa.String(), nullable=True))
        if not _column_exists('dfd_sessions', 'progress_percent'):
            op.add_column('dfd_sessions', sa.Column('progress_percent', sa.Float(), nullable=True, server_default='0'))


def downgrade() -> None:
    """Remove pipeline_stage_logs table and progress columns."""
    if _table_exists('pipeline_stage_logs'):
        op.drop_table('pipeline_stage_logs')

    if _table_exists('dfd_sessions'):
        if _column_exists('dfd_sessions', 'current_stage'):
            op.drop_column('dfd_sessions', 'current_stage')
        if _column_exists('dfd_sessions', 'progress_percent'):
            op.drop_column('dfd_sessions', 'progress_percent')
