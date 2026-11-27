from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0006_clarifications"
down_revision: Final[str] = "0005_requirements"
branch_labels: Final[None] = None
depends_on: Final[None] = None


def upgrade() -> None:
    create_runs()
    op.create_table(
        "clarification_questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("history_id", sa.Uuid(), nullable=False),
        sa.Column("gap_key", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("task_id", "history_id", "gap_key"),
    )
    op.create_table(
        "clarification_question_revisions",
        sa.Column(
            "question_id", sa.Uuid(), sa.ForeignKey("clarification_questions.id"), primary_key=True
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "clarification_question_links",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("clarification_runs.run_id"), primary_key=True
        ),
        sa.Column(
            "question_id", sa.Uuid(), sa.ForeignKey("clarification_questions.id"), primary_key=True
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("requirement_ids_json", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "clarification_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "question_id", sa.Uuid(), sa.ForeignKey("clarification_questions.id"), nullable=False
        ),
        sa.Column("question_revision", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("clarification_runs.run_id"), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("question_id", "question_revision"),
    )
    op.create_table(
        "clarification_risks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Uuid(),
            sa.ForeignKey("clarification_decisions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "clarification_operations",
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
    )


def create_runs() -> None:
    op.create_table(
        "clarification_runs",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("requirements_extractions.id"), primary_key=True
        ),
        sa.Column("history_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("initialized", sa.Boolean(), nullable=False),
        sa.Column("resume_pending", sa.Boolean(), nullable=False),
        sa.Column("resume_version", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("completed_json", sa.Text(), nullable=False),
        sa.Column("active_seconds", sa.Float(), nullable=False),
        sa.Column("active_started", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    table: str
    for table in (
        "clarification_operations",
        "clarification_risks",
        "clarification_decisions",
        "clarification_question_links",
        "clarification_question_revisions",
        "clarification_questions",
        "clarification_runs",
    ):
        op.drop_table(table)
