from typing import Final

from alembic import op

revision: Final[str] = "0003_unique_answer"
down_revision: Final[str | None] = "0002_profile"
branch_labels: Final[None] = None
depends_on: Final[None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_runs_assistant_message_id", "runs", ["assistant_message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_runs_assistant_message_id", "runs", type_="unique")
