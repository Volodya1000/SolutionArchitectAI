from alembic import context
from sqlalchemy.engine import Connection

from solution_architect_ai.persistence.models import Base


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


run_migrations(context.config.attributes["connection"])
