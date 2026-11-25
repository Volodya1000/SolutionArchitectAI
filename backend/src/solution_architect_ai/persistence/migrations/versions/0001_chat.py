import sqlalchemy as sa
from alembic import op

revision = "0001_chat"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
    )
    op.create_table(
        "chats",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("chat_id", sa.Uuid(), sa.ForeignKey("chats.id"), nullable=False, index=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("incomplete", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("chat_id", "position"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("chat_id", sa.Uuid(), sa.ForeignKey("chats.id"), nullable=False, index=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, index=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("incomplete", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column("model", sa.Text(), nullable=False),
        sa.UniqueConstraint("chat_id", "command_id"),
    )
    op.create_table(
        "preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("theme", sa.Text(), nullable=False),
    )
    op.execute(
        "INSERT INTO projects VALUES ('10000000-0000-4000-8000-000000000001', 'Локальный проект')"
    )
    op.execute(
        "INSERT INTO tasks VALUES ('10000000-0000-4000-8000-000000000002', "
        "'10000000-0000-4000-8000-000000000001', 'Обсуждение архитектуры')"
    )
    op.execute("INSERT INTO preferences VALUES (1, 'system')")


def downgrade() -> None:
    for table in ("preferences", "runs", "messages", "chats", "tasks", "projects"):
        op.drop_table(table)
