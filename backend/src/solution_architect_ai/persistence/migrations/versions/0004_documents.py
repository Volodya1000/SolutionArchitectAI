from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0004_documents"
down_revision: Final[str | None] = "0003_unique_answer"
branch_labels: Final[None] = None
depends_on: Final[None] = None


def upgrade() -> None:
    create_documents()
    create_uploads()
    create_parses()
    op.create_table(
        "message_document_versions",
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id"), primary_key=True),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("document_versions.version_id"), primary_key=True
        ),
    )


def create_documents() -> None:
    op.create_table(
        "documents",
        sa.Column("file_id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "document_versions",
        sa.Column("version_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "file_id", sa.Uuid(), sa.ForeignKey("documents.file_id"), nullable=False, index=True
        ),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.CheckConstraint("size > 0", name="ck_document_version_size"),
    )


def create_uploads() -> None:
    op.create_table(
        "document_uploads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("version_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("task_id", "operation_id"),
    )


def create_parses() -> None:
    op.create_table(
        "parsed_documents",
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("document_versions.version_id"), primary_key=True
        ),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
    )
    op.create_table(
        "document_fragments",
        sa.Column("fragment_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("parsed_documents.version_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("message_document_versions")
    op.drop_table("document_fragments")
    op.drop_table("parsed_documents")
    op.drop_table("document_uploads")
    op.drop_table("document_versions")
    op.drop_table("documents")
