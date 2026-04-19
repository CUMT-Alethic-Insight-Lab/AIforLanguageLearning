"""link analytics events to users

Revision ID: 4a8d7d7c2f11
Revises: 98ed1e32bf23
Create Date: 2026-04-18 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4a8d7d7c2f11"
down_revision: Union[str, Sequence[str], None] = "98ed1e32bf23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversation_events", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_conversation_events_user_id"), "conversation_events", ["user_id"], unique=False)

    op.add_column("essay_submissions", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_essay_submissions_user_id"), "essay_submissions", ["user_id"], unique=False)

    op.add_column("user_vocab_queries", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("user_vocab_queries", sa.Column("metadata", sa.JSON(), nullable=True))
    op.create_index(op.f("ix_user_vocab_queries_user_id"), "user_vocab_queries", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_vocab_queries_user_id"), table_name="user_vocab_queries")
    op.drop_column("user_vocab_queries", "metadata")
    op.drop_column("user_vocab_queries", "user_id")

    op.drop_index(op.f("ix_essay_submissions_user_id"), table_name="essay_submissions")
    op.drop_column("essay_submissions", "user_id")

    op.drop_index(op.f("ix_conversation_events_user_id"), table_name="conversation_events")
    op.drop_column("conversation_events", "user_id")
