from collections.abc import Awaitable, Callable

import psycopg
from sqlalchemy.exc import DBAPIError
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_fixed

from solution_architect_ai.application.protocols.transaction_protocols import (
    TransactionRetriesExhausted,
)


def transaction_conflict(error: BaseException) -> bool:
    return (
        isinstance(error, DBAPIError)
        and isinstance(error.orig, psycopg.Error)
        and error.orig.sqlstate in {"40P01", "40001"}
    )


class SqlTransactionRunner:
    """Replay a complete rolled-back SQL transaction, never an external operation."""

    async def run[ResultT](self, operation: Callable[[], Awaitable[ResultT]]) -> ResultT:
        retrying: AsyncRetrying = AsyncRetrying(
            retry=retry_if_exception(transaction_conflict),
            stop=stop_after_attempt(3),
            wait=wait_fixed(0.05),
            reraise=True,
        )
        try:
            return await retrying(operation)
        except DBAPIError as error:
            if not transaction_conflict(error):
                raise
            raise TransactionRetriesExhausted("transaction_conflict") from error
