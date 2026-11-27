import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import database_url


def upgrade(connection: Connection) -> None:
    config: Config = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def migrate() -> None:
    settings: Settings = bootstrap()
    engine: AsyncEngine = create_async_engine(database_url(settings))
    try:
        connection: AsyncConnection
        async with engine.begin() as connection:
            await connection.run_sync(upgrade)
    finally:
        await engine.dispose()
    saver: AsyncPostgresSaver
    dsn: str = (
        database_url(settings).set(drivername="postgresql").render_as_string(hide_password=False)
    )
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()


if __name__ == "__main__":
    asyncio.run(migrate(), loop_factory=asyncio.SelectorEventLoop)
