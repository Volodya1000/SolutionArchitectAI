from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0008_review_steps"
down_revision: Final[str] = "0007_discussions"
branch_labels: Final[None] = None
depends_on: Final[None] = None


def upgrade() -> None:
    op.create_table(
        "clarification_review_steps",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("requirements_extractions.id"), primary_key=True
        ),
        sa.Column("step_key", sa.String(64), primary_key=True),
        sa.Column("result_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("clarification_review_steps")
