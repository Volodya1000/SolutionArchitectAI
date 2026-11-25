import asyncio
import tempfile
from pathlib import Path

from solution_architect_ai.application.contracts import StorageUnavailable


class LocalResourceProbe:
    def __init__(self, directories: tuple[Path, ...]) -> None:
        self.directories = directories

    def check_directories(self) -> None:
        for directory in self.directories:
            with tempfile.TemporaryFile(dir=directory) as probe:
                probe.write(b"readiness")
                probe.flush()

    async def check(self) -> None:
        try:
            await asyncio.to_thread(self.check_directories)
        except OSError:
            raise StorageUnavailable("durable_storage_unavailable") from None
