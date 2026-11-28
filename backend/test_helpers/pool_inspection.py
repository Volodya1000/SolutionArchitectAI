from sqlalchemy import AsyncAdaptedQueuePool, Pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
)


def checked_out(engine: AsyncEngine) -> int:
    pool: Pool = engine.pool
    assert isinstance(pool, AsyncAdaptedQueuePool)
    return pool.checkedout()
