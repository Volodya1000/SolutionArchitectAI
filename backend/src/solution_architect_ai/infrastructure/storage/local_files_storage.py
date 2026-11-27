import asyncio
import os
import re
from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path, PurePath, PureWindowsPath
from typing import BinaryIO, Final, Protocol
from uuid import uuid4

from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.application.protocols.document_protocols import StagedFile

_KEY: Final[re.Pattern[str]] = re.compile(r"[0-9a-f-]{36}/[0-9a-f-]{36}\Z")
_TEMP: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{32}\Z")


def comparison_path(path: PurePath) -> PurePath:
    """Compare Windows paths returned by filesystem APIs, including extended paths."""
    if not isinstance(path, PureWindowsPath):
        return path
    value: str = str(path)
    if value[:8].casefold() == "\\\\?\\unc\\":
        return PureWindowsPath("\\\\" + value[8:])
    if value.startswith("\\\\?\\") and re.fullmatch(r"[A-Za-z]:", path.drive[4:]):
        return PureWindowsPath(value[4:])
    return path


class ContentHasher(Protocol):
    def update(self, data: bytes, /) -> None: ...
    def hexdigest(self) -> str: ...


class LocalFileStorage:
    def __init__(self, root: Path, *, max_bytes: int = 20 * 1024 * 1024) -> None:
        self.root: Path = root.resolve()
        self.max_bytes: int = max_bytes

    def path(self, key: str, *, temporary: bool = False) -> Path:
        pattern: re.Pattern[str] = _TEMP if temporary else _KEY
        if not pattern.fullmatch(key):
            raise DocumentFailure(DocumentErrorCode.INVALID_KEY)
        base: Path = self.root / ".pending" if temporary else self.root
        target: Path = base / key
        if not comparison_path(target.resolve()).is_relative_to(comparison_path(self.root)):
            raise DocumentFailure(DocumentErrorCode.INVALID_KEY)
        if target.is_symlink() or target.parent.is_symlink():
            raise DocumentFailure(DocumentErrorCode.INVALID_KEY)
        return target

    async def stage(self, chunks: AsyncIterator[bytes]) -> StagedFile:
        key: str = uuid4().hex
        path: Path = self.path(key, temporary=True)
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            return await self.write_staged(path, key, chunks)
        except BaseException as error:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            if isinstance(error, OSError):
                raise DocumentFailure(DocumentErrorCode.STORAGE_UNAVAILABLE) from None
            raise

    async def write_staged(self, path: Path, key: str, chunks: AsyncIterator[bytes]) -> StagedFile:
        stream: BinaryIO = await asyncio.to_thread(path.open, "xb")
        try:
            staged_file: StagedFile = await self.consume(stream, key, chunks)
            await asyncio.to_thread(stream.flush)
            await asyncio.to_thread(os.fsync, stream.fileno())
            return staged_file
        finally:
            await asyncio.to_thread(stream.close)

    async def consume(self, stream: BinaryIO, key: str, chunks: AsyncIterator[bytes]) -> StagedFile:
        size: int = 0
        digest: ContentHasher = sha256()
        chunk: bytes
        async for chunk in chunks:
            size += len(chunk)
            if size > self.max_bytes:
                raise DocumentFailure(DocumentErrorCode.TOO_LARGE)
            digest.update(chunk)
            await asyncio.to_thread(stream.write, chunk)
        if size == 0:
            raise DocumentFailure(DocumentErrorCode.EMPTY)
        return StagedFile(key, size, digest.hexdigest())

    async def staged_content(self, staged_file: StagedFile) -> bytes:
        return await asyncio.to_thread(
            self.read_verified,
            self.path(staged_file.temporary_key, temporary=True),
            staged_file.size,
            staged_file.sha256,
        )

    async def discard(self, staged_file: StagedFile) -> None:
        await asyncio.to_thread(
            self.path(staged_file.temporary_key, temporary=True).unlink, missing_ok=True
        )

    async def publish(self, staged_file: StagedFile, storage_key: str) -> None:
        source: Path = self.path(staged_file.temporary_key, temporary=True)
        target: Path = self.path(storage_key)
        await asyncio.to_thread(self.read_verified, source, staged_file.size, staged_file.sha256)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(os.link, source, target)
        except FileExistsError:
            try:
                await self.read(storage_key, staged_file.size, staged_file.sha256)
            except DocumentFailure:
                raise DocumentFailure(DocumentErrorCode.FILE_CONFLICT) from None
        except OSError:
            raise DocumentFailure(DocumentErrorCode.STORAGE_UNAVAILABLE) from None

    def read_verified(self, path: Path, size: int, digest: str) -> bytes:
        if size < 1 or size > self.max_bytes:
            raise DocumentFailure(DocumentErrorCode.TOO_LARGE)
        try:
            stream: BinaryIO
            with path.open("rb") as stream:
                content: bytes = stream.read(size + 1)
        except FileNotFoundError:
            raise DocumentFailure(DocumentErrorCode.MISSING_FILE) from None
        except OSError:
            raise DocumentFailure(DocumentErrorCode.STORAGE_UNAVAILABLE) from None
        if len(content) != size or sha256(content).hexdigest() != digest:
            raise DocumentFailure(DocumentErrorCode.CORRUPT_FILE)
        return content

    async def read(self, storage_key: str, size: int, digest: str) -> bytes:
        return await asyncio.to_thread(self.read_verified, self.path(storage_key), size, digest)
