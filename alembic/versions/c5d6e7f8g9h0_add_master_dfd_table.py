"""add master_dfd table

Revision ID: c5d6e7f8g9h0
Revises: b1c2d3e4f5a6
Create Date: 2026-03-23 19:58:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c5d6e7f8g9h0'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    """Create master_dfds table for project-level DFD aggregation."""
    if not _table_exists('master_dfds'):
        op.create_table(
            'master_dfds',
            sa.Column('project_id', sa.String(), nullable=False),
            sa.Column('session_ids', sa.JSON(), nullable=False),
            sa.Column('status', sa.String(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('master_kg_json', sa.JSON(), nullable=True),
            sa.Column('master_render_plan_json', sa.JSON(), nullable=True),
            sa.Column('master_html', sa.Text(), nullable=True),
            sa.Column('overview_summary', sa.JSON(), nullable=True),
            sa.Column('project_name', sa.String(), nullable=True),
            sa.Column('total_sessions', sa.Integer(), nullable=True),
            sa.Column('total_nodes', sa.Integer(), nullable=True),
            sa.Column('total_edges', sa.Integer(), nullable=True),
            sa.Column('total_risks', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('project_id')
        )
        op.create_index(op.f('ix_master_dfds_project_id'), 'master_dfds', ['project_id'], unique=False)
        op.create_index(op.f('ix_master_dfds_status'), 'master_dfds', ['status'], unique=False)
        print("✅ Created master_dfds table")
    else:
        print("⚠️  master_dfds table already exists, skipping")


def downgrade():
    """Drop master_dfds table."""
    if _table_exists('master_dfds'):
        op.drop_index(op.f('ix_master_dfds_status'), table_name='master_dfds')
        op.drop_index(op.f('ix_master_dfds_project_id'), table_name='master_dfds')
        op.drop_table('master_dfds')
        print("✅ Dropped master_dfds table")
    else:
        print("⚠️  master_dfds table does not exist, skipping")
