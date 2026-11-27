from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0007_discussions"
down_revision: Final[str] = "0006_clarifications"
branch_labels: Final[None] = None
depends_on: Final[None] = None


def upgrade() -> None:
    op.create_table(
        "discussions",
        sa.Column("chat_id", sa.Uuid(), sa.ForeignKey("chats.id"), primary_key=True),
        sa.Column("binding_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "discussion_operations",
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("command_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("discussion_operations")
    op.drop_table("discussions")
