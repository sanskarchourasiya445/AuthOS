"""create agent_proposals table for Phase 8 multi-agent workflow

Revision ID: e4f5a6b7c8d9
Revises: c3e1a29f8812
Create Date: 2026-10-10 10:37:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'c3e1a29f8812'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = insp.get_table_names()

    if 'agent_proposals' not in existing_tables:
        op.create_table(
            'agent_proposals',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('case_id', sa.String(length=64), nullable=False),
            sa.Column('run_id', sa.String(length=64), nullable=False),
            sa.Column('criterion_id', sa.String(length=32), nullable=False),
            sa.Column('proposed_status', sa.String(length=32), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=False, server_default='0.0'),
            sa.Column('uncertainty_rationale', sa.Text(), nullable=False),
            sa.Column('evidence_quotes', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column('missing_facts', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column('detected_gaps', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column('retrieval_rounds', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('verification_feedback', sa.JSON(), nullable=True),
            sa.Column('flags', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('case_id', 'run_id', 'criterion_id', name='uq_case_run_criterion'),
        )
        op.create_index(op.f('ix_agent_proposals_case_id'), 'agent_proposals', ['case_id'], unique=False)
        op.create_index(op.f('ix_agent_proposals_run_id'), 'agent_proposals', ['run_id'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = insp.get_table_names()

    if 'agent_proposals' in existing_tables:
        op.drop_index(op.f('ix_agent_proposals_run_id'), table_name='agent_proposals')
        op.drop_index(op.f('ix_agent_proposals_case_id'), table_name='agent_proposals')
        op.drop_table('agent_proposals')
