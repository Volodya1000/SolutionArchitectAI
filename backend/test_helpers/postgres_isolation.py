"""A migrated database per test, retaining independent real transactions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from psycopg import AsyncConnection, sql

from solution_architect_ai.config.models import DatabaseSettings


@asynccontextmanager
async def isolated_test_database(settings: DatabaseSettings) -> AsyncIterator[str]:
    if not settings.database.endswith("_test"):
        raise ValueError("Database isolation requires a dedicated migrated _test template")
    name: str = f"saa_{uuid4().hex}_test"
    connection: AsyncConnection[tuple[object, ...]] = await AsyncConnection.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.credentials.password.get_secret_value(),
        dbname="postgres",
        autocommit=True,
    )
    async with connection:
        await connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(settings.database)
            )
        )
        try:
            yield name
        finally:
            await connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
