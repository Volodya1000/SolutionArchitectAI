import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import database_url


def upgrade(connection: Connection) -> None:
    config = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def migrate() -> None:
    engine = create_async_engine(database_url(bootstrap()))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(upgrade)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate(), loop_factory=asyncio.SelectorEventLoop)
