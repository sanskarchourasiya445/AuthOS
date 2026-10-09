"""add conflicting_evidence to criterion_results

Revision ID: c3e1a29f8812
Revises: fba7fd4a1357
Create Date: 2026-10-10 01:17:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e1a29f8812'
down_revision: Union[str, Sequence[str], None] = 'fba7fd4a1357'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_cols = [c['name'] for c in insp.get_columns('criterion_results')]
    if 'conflicting_evidence' not in existing_cols:
        op.add_column(
            'criterion_results',
            sa.Column('conflicting_evidence', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_cols = [c['name'] for c in insp.get_columns('criterion_results')]
    if 'conflicting_evidence' in existing_cols:
        op.drop_column('criterion_results', 'conflicting_evidence')
