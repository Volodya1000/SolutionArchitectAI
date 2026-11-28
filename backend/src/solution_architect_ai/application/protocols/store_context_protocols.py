from contextlib import AbstractAsyncContextManager
from typing import Protocol


class StoreContext[StoreT](Protocol):
    def open(self) -> AbstractAsyncContextManager[StoreT]: ...
