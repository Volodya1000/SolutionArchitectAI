from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0002_profile"
down_revision: Final[str | None] = "0001_chat"
branch_labels: Final[None] = None
depends_on: Final[None] = None


def upgrade() -> None:
    op.add_column(
        "runs", sa.Column("config_digest", sa.Text(), nullable=False, server_default="legacy")
    )
    op.add_column(
        "runs",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "created_at")
    op.drop_column("runs", "config_digest")
