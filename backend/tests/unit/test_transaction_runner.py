import asyncio
from typing import Final

import psycopg
import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError

from solution_architect_ai.application.protocols.transaction_protocols import (
    TransactionRetriesExhausted,
)
from solution_architect_ai.persistence.transaction_runner import SqlTransactionRunner

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
async def test_retry_budget_is_bounded_and_preserves_the_database_cause(sqlstate: str) -> None:
    attempts: int = 0
    failure: DBAPIError = OperationalError(None, None, psycopg.errors.lookup(sqlstate)())

    async def conflicting_transaction() -> None:
        nonlocal attempts
        attempts += 1
        raise failure

    raised: pytest.ExceptionInfo[TransactionRetriesExhausted]
    with pytest.raises(TransactionRetriesExhausted) as raised:
        await SqlTransactionRunner().run(conflicting_transaction)
    assert attempts == 3
    assert raised.value.__cause__ is failure


@pytest.mark.parametrize(
    "failure",
    [
        IntegrityError(None, None, psycopg.errors.UniqueViolation()),
        ProgrammingError(None, None, psycopg.errors.SyntaxError()),
        RuntimeError("unknown"),
    ],
)
async def test_unrelated_failures_are_not_retried_or_hidden(failure: Exception) -> None:
    attempts: int = 0

    async def transaction() -> None:
        nonlocal attempts
        attempts += 1
        raise failure

    raised: pytest.ExceptionInfo[Exception]
    with pytest.raises(type(failure)) as raised:
        await SqlTransactionRunner().run(transaction)
    assert raised.value is failure
    assert attempts == 1


async def test_shutdown_cancels_backoff_without_another_transaction() -> None:
    failed: asyncio.Event = asyncio.Event()
    attempts: int = 0

    async def transaction() -> None:
        nonlocal attempts
        attempts += 1
        failed.set()
        raise OperationalError(None, None, psycopg.errors.DeadlockDetected())

    task: asyncio.Task[None] = asyncio.create_task(SqlTransactionRunner().run(transaction))
    await failed.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert attempts == 1
