"""add cascade delete to chunks parent_id fk

Revision ID: f637d4cd5c8d
Revises: a66500b37563
Create Date: 2026-06-24 08:19:50.825146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f637d4cd5c8d'
down_revision: Union[str, Sequence[str], None] = 'a66500b37563'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f('chunks_parent_id_fkey'), 'chunks', type_='foreignkey')
    op.create_foreign_key(None, 'chunks', 'chunks', ['parent_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint(None, 'chunks', type_='foreignkey')
    op.create_foreign_key(op.f('chunks_parent_id_fkey'), 'chunks', 'chunks', ['parent_id'], ['id'])
