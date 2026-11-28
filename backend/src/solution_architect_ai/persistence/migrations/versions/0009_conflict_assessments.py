from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0009_conflict_assessments"
down_revision: Final[str] = "0008_review_steps"
branch_labels: Final[None] = None
depends_on: Final[None] = None


def upgrade() -> None:
    op.add_column(
        "clarification_runs",
        sa.Column("assessments_json", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("clarification_runs", "assessments_json")
