from typing import Final

import psycopg
import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InvalidRequestError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.persistence.store_context import SqlAlchemyStoreContext

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio


@pytest.mark.parametrize(
    "failure",
    [
        IntegrityError(None, None, psycopg.errors.UniqueViolation()),
        ProgrammingError(None, None, psycopg.errors.SyntaxError()),
        OperationalError(None, None, psycopg.errors.DeadlockDetected()),
        OperationalError(None, None, psycopg.errors.QueryCanceled()),
        InvalidRequestError("invalid transaction"),
        SQLAlchemyError("unexpected SQLAlchemy failure"),
    ],
)
async def test_non_availability_errors_retain_identity(failure: SQLAlchemyError) -> None:
    context: SqlAlchemyStoreContext[AsyncSession] = SqlAlchemyStoreContext(
        async_sessionmaker(), lambda session: session
    )
    with pytest.raises(type(failure)) as raised:
        async with context.open():
            raise failure
    assert raised.value is failure


@pytest.mark.parametrize(
    "failure",
    [
        OperationalError(None, None, psycopg.OperationalError("connection refused")),
        OperationalError(None, None, psycopg.errors.TooManyConnections()),
        OperationalError(None, None, psycopg.errors.AdminShutdown()),
        DBAPIError(None, None, psycopg.InterfaceError(), connection_invalidated=True),
    ],
)
async def test_database_availability_failures_are_translated(failure: DBAPIError) -> None:
    context: SqlAlchemyStoreContext[AsyncSession] = SqlAlchemyStoreContext(
        async_sessionmaker(), lambda session: session
    )
    with pytest.raises(StorageUnavailable, match="database_unavailable"):
        async with context.open():
            raise failure


async def test_input_validation_error_is_not_translated() -> None:
    context: SqlAlchemyStoreContext[AsyncSession] = SqlAlchemyStoreContext(
        async_sessionmaker(), lambda session: session
    )
    with pytest.raises(ValidationError):
        async with context.open():
            TypeAdapter(int).validate_python("invalid input")


async def test_caller_timeout_is_not_mistaken_for_session_timeout() -> None:
    context: SqlAlchemyStoreContext[AsyncSession] = SqlAlchemyStoreContext(
        async_sessionmaker(), lambda session: session
    )
    failure: TimeoutError = TimeoutError("caller deadline")
    with pytest.raises(TimeoutError) as raised:
        async with context.open():
            raise failure
    assert raised.value is failure
