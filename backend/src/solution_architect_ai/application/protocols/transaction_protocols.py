from collections.abc import Awaitable, Callable
from typing import Protocol


class TransactionRetriesExhausted(Exception):
    pass


class TransactionRunner(Protocol):
    async def run[ResultT](self, operation: Callable[[], Awaitable[ResultT]]) -> ResultT: ...


class DirectTransactionRunner:
    async def run[ResultT](self, operation: Callable[[], Awaitable[ResultT]]) -> ResultT:
        return await operation()
