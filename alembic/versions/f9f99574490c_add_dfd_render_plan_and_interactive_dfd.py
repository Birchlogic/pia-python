"""add_dfd_render_plan_and_interactive_dfd

Revision ID: f9f99574490c
Revises: a4d05bca6146
Create Date: 2026-03-10 17:24:52.402174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'f9f99574490c'
down_revision: Union[str, Sequence[str], None] = 'a4d05bca6146'
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
    """Upgrade schema — safe idempotent migration."""

    # 1. Create tables only if they don't exist
    if not _table_exists('dfd_sessions'):
        op.create_table('dfd_sessions',
            sa.Column('session_id', sa.String(), nullable=False),
            sa.Column('department', sa.String(), nullable=True),
            sa.Column('status', sa.String(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('schema_one_json', sa.JSON(), nullable=True),
            sa.Column('dfd_json', sa.JSON(), nullable=True),
            sa.Column('privacy_dfd_md', sa.Text(), nullable=True),
            sa.Column('processing_mode', sa.String(), nullable=True),
            sa.Column('actors_json', sa.JSON(), nullable=True),
            sa.Column('systems_json', sa.JSON(), nullable=True),
            sa.Column('data_elements_json', sa.JSON(), nullable=True),
            sa.Column('flows_json', sa.JSON(), nullable=True),
            sa.Column('risks_json', sa.JSON(), nullable=True),
            sa.Column('compliance_schema_json', sa.JSON(), nullable=True),
            sa.Column('verification_report_json', sa.JSON(), nullable=True),
            sa.Column('interactive_html', sa.Text(), nullable=True),
            sa.Column('dfd_render_plan_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('session_id')
        )

    if not _table_exists('data_mapping_rows'):
        op.create_table('data_mapping_rows',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('session_id', sa.String(), nullable=False),
            sa.Column('s_no', sa.Integer(), nullable=False),
            sa.Column('data_category', sa.String(), nullable=False),
            sa.Column('description', sa.String(), nullable=False),
            sa.Column('purpose', sa.String(), nullable=False),
            sa.Column('data_owner', sa.String(), nullable=False),
            sa.Column('storage_location', sa.String(), nullable=False),
            sa.Column('data_classification', sa.String(), nullable=False),
            sa.Column('retention_period', sa.String(), nullable=False),
            sa.Column('legal_basis', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

    if not _table_exists('interactive_dfds'):
        op.create_table('interactive_dfds',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('nodes', sa.JSON(), nullable=False),
            sa.Column('edges', sa.JSON(), nullable=False),
            sa.Column('levels', sa.JSON(), nullable=False),
            sa.Column('pipeline_docs', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

    if not _table_exists('kg_nodes'):
        op.create_table('kg_nodes',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('session_id', sa.String(), nullable=False),
            sa.Column('node_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('type', sa.String(), nullable=False),
            sa.Column('aliases', sa.JSON(), nullable=True),
            sa.Column('data_elements', sa.JSON(), nullable=True),
            sa.Column('risks', sa.JSON(), nullable=True),
            sa.Column('sources', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

    if not _table_exists('kg_edges'):
        op.create_table('kg_edges',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('session_id', sa.String(), nullable=False),
            sa.Column('source_node', sa.String(), nullable=False),
            sa.Column('target_node', sa.String(), nullable=False),
            sa.Column('data_elements', sa.JSON(), nullable=True),
            sa.Column('flow_type', sa.String(), nullable=True),
            sa.Column('channel', sa.String(), nullable=True),
            sa.Column('inferred', sa.Integer(), nullable=True),
            sa.Column('sources', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

    # 2. Add new columns to existing tables (safe — checks first)
    if _table_exists('dfd_sessions') and not _column_exists('dfd_sessions', 'dfd_render_plan_json'):
        op.add_column('dfd_sessions', sa.Column('dfd_render_plan_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    if _table_exists('dfd_sessions') and _column_exists('dfd_sessions', 'dfd_render_plan_json'):
        op.drop_column('dfd_sessions', 'dfd_render_plan_json')
