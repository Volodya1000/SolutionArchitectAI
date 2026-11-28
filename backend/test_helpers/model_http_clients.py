"""Real SDK clients with controlled transports and no ambient proxy configuration."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ModelHttpClients:
    asynchronous: httpx.AsyncClient
    synchronous: httpx.Client


def reject_sync_request(_request: httpx.Request) -> httpx.Response:
    raise AssertionError("The async SDK unexpectedly used its synchronous transport")


@asynccontextmanager
async def model_http_clients(
    handler: Callable[[httpx.Request], httpx.Response],
) -> AsyncIterator[ModelHttpClients]:
    with httpx.Client(
        transport=httpx.MockTransport(reject_sync_request), trust_env=False
    ) as synchronous:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as asynchronous:
            yield ModelHttpClients(asynchronous, synchronous)
