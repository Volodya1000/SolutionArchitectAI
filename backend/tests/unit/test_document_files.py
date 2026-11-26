import asyncio
from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from solution_architect_ai.application.document_errors import DocumentErrorCode, DocumentFailure
from solution_architect_ai.application.document_ports import StagedFile
from solution_architect_ai.infrastructure.files import LocalFileStorage


async def chunks(value: bytes) -> AsyncIterator[bytes]:
    yield value


@pytest.mark.anyio
async def test_storage_publishes_immutable_verified_content(tmp_path: Path) -> None:
    storage: LocalFileStorage = LocalFileStorage(tmp_path, max_bytes=32)
    staged: StagedFile = await storage.stage(chunks(b"original"))
    key: str = f"{uuid4()}/{uuid4()}"
    await storage.publish(staged, key)
    assert await storage.read(key, len(b"original"), sha256(b"original").hexdigest()) == b"original"
    replacement: StagedFile = await storage.stage(chunks(b"replacement"))
    with pytest.raises(DocumentFailure):
        await storage.publish(replacement, key)
    assert await storage.read(key, 8, sha256(b"original").hexdigest()) == b"original"


@pytest.mark.anyio
async def test_storage_size_traversal_and_corruption_are_rejected(tmp_path: Path) -> None:
    storage: LocalFileStorage = LocalFileStorage(tmp_path, max_bytes=8)
    with pytest.raises(DocumentFailure):
        await storage.stage(chunks(b"too long!"))
    with pytest.raises(DocumentFailure):
        await storage.read("../../private", 1, "0" * 64)
    staged: StagedFile = await storage.stage(chunks(b"data"))
    key: str = f"{uuid4()}/{uuid4()}"
    await storage.publish(staged, key)
    with pytest.raises(DocumentFailure):
        await storage.read(key, 4, "0" * 64)
    with pytest.raises(DocumentFailure):
        await storage.read(f"{uuid4()}/{uuid4()}", 4, "0" * 64)


@pytest.mark.anyio
async def test_cancelled_upload_cleans_its_temporary_file(tmp_path: Path) -> None:
    storage: LocalFileStorage = LocalFileStorage(tmp_path)

    async def interrupted() -> AsyncIterator[bytes]:
        yield b"partial"
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await storage.stage(interrupted())
    assert not await asyncio.to_thread(lambda: list((tmp_path / ".pending").iterdir()))


@pytest.mark.anyio
async def test_storage_permission_failure_has_typed_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage: LocalFileStorage = LocalFileStorage(tmp_path)

    def denied(_path: Path, _mode: str) -> None:
        raise PermissionError("injected unwritable disk")

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(DocumentFailure) as error:
        await storage.stage(chunks(b"content"))
    assert error.value.code == DocumentErrorCode.STORAGE_UNAVAILABLE
