from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0005_requirements"
down_revision: Final[str] = "0004_documents"
branch_labels: Final[None] = None
depends_on: Final[None] = None


def upgrade() -> None:
    create_extractions()
    op.create_table(
        "requirements_extraction_parts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("requirements_extractions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("part_id", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_id", "part_id"),
    )
    op.create_table(
        "requirements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("requirements_extractions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text(), nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False),
    )
    op.create_table(
        "requirements_extraction_sources",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("requirements_extractions.id"), primary_key=True
        ),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("document_versions.version_id"), primary_key=True
        ),
    )


def create_extractions() -> None:
    op.create_table(
        "requirements_extractions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("config_digest", sa.Text(), nullable=False),
        sa.Column("context_digest", sa.Text(), nullable=True),
        sa.Column("command_json", sa.Text(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, index=True),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("network_failures", sa.Integer(), nullable=False),
        sa.Column("corrections", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "operation_id"),
        sa.CheckConstraint("requests >= 0", name="ck_extraction_request_count"),
    )


def downgrade() -> None:
    op.drop_table("requirements_extraction_sources")
    op.drop_table("requirements")
    op.drop_table("requirements_extraction_parts")
    op.drop_table("requirements_extractions")
