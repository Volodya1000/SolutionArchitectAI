import asyncio
import tempfile
from pathlib import Path
from typing import IO

from solution_architect_ai.application.errors import StorageUnavailable


class LocalResourceProbe:
    def __init__(self, directories: tuple[Path, ...]) -> None:
        self.directories: tuple[Path, ...] = directories

    def check_directories(self) -> None:
        directory: Path
        for directory in self.directories:
            probe: IO[bytes]
            with tempfile.TemporaryFile(dir=directory) as probe:
                probe.write(b"readiness")
                probe.flush()

    async def check(self) -> None:
        try:
            await asyncio.to_thread(self.check_directories)
        except OSError:
            raise StorageUnavailable("durable_storage_unavailable") from None
