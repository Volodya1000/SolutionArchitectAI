from alembic import op

revision = "0003_unique_answer"
down_revision = "0002_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_runs_assistant_message_id", "runs", ["assistant_message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_runs_assistant_message_id", "runs", type_="unique")
