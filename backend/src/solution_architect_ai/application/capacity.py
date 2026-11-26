import asyncio


class GenerationCapacity:
    def __init__(self, concurrency: int) -> None:
        self.slots: asyncio.Semaphore = asyncio.Semaphore(concurrency)
