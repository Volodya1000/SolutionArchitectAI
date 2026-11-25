import sqlalchemy as sa
from alembic import op

revision = "0002_profile"
down_revision = "0001_chat"
branch_labels = None
depends_on = None


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
