import asyncio


class GenerationCapacity:
    def __init__(self, concurrency: int) -> None:
        self.concurrency: int = concurrency
        self.slots: asyncio.Semaphore = asyncio.Semaphore(concurrency)
