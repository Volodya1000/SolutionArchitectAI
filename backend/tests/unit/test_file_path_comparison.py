import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

import pytest

from solution_architect_ai.application.document_errors import DocumentErrorCode, DocumentFailure
from solution_architect_ai.infrastructure.files import LocalFileStorage, comparison_path


@pytest.mark.skipif(os.name != "nt", reason="Windows extended drive representation")
def test_equivalent_extended_canonical_target_stays_inside_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage: LocalFileStorage = LocalFileStorage(tmp_path)
    key: str = uuid4().hex
    target: Path = storage.root / ".pending" / key
    original: Callable[[Path, bool], Path] = Path.resolve

    def resolved_with_extended_prefix(path: Path, *, strict: bool = False) -> Path:
        result: Path = original(path, strict)
        return Path("\\\\?\\" + str(result)) if path == target else result

    monkeypatch.setattr(Path, "resolve", resolved_with_extended_prefix)
    assert storage.path(key, temporary=True) == target


def test_canonical_target_outside_storage_is_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage: LocalFileStorage = LocalFileStorage(tmp_path)
    key: str = uuid4().hex
    target: Path = storage.root / ".pending" / key
    outside: Path = storage.root.parent / "outside-storage" / key
    original: Callable[[Path, bool], Path] = Path.resolve

    def resolved_outside(path: Path, *, strict: bool = False) -> Path:
        return outside if path == target else original(path, strict)

    monkeypatch.setattr(Path, "resolve", resolved_outside)
    with pytest.raises(DocumentFailure) as error:
        storage.path(key, temporary=True)
    assert error.value.code == DocumentErrorCode.INVALID_KEY


def test_symlinked_parent_cannot_escape_storage(tmp_path: Path) -> None:
    storage: LocalFileStorage = LocalFileStorage(tmp_path)
    outside: Path = tmp_path.parent / f"outside-{uuid4().hex}"
    outside.mkdir()
    parent: Path = storage.root / str(uuid4())
    try:
        parent.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        if os.name == "nt" and error.winerror == 1314:
            pytest.skip("Windows user does not hold symlink creation privilege")
        raise
    with pytest.raises(DocumentFailure) as failure:
        storage.path(f"{parent.name}/{uuid4()}")
    assert failure.value.code == DocumentErrorCode.INVALID_KEY


@pytest.mark.parametrize(
    ("root", "target", "contained"),
    [
        (r"C:\files", r"\\?\C:\files\version", True),
        (r"\\?\C:\files", r"C:\files\version", True),
        (r"\\server\share\files", r"\\?\UNC\server\share\files\version", True),
        (r"\\?\UNC\server\share\files", r"\\server\share\files\version", True),
        (r"\\server\share\files", r"\\?\unc\SERVER\SHARE\files\version", True),
        (r"C:\files", r"\\?\C:\files-other\version", False),
        (r"C:\files", r"\\?\D:\files\version", False),
        (r"\\server\share\files", r"\\?\UNC\other\share\files\version", False),
        (r"\\server\share\files", r"\\?\UNC\server\other\files\version", False),
    ],
)
def test_only_equivalent_windows_namespaces_share_containment(
    root: str, target: str, contained: bool
) -> None:
    canonical_root: PureWindowsPath = PureWindowsPath(root)
    canonical_target: PureWindowsPath = PureWindowsPath(target)
    assert (
        comparison_path(canonical_target).is_relative_to(comparison_path(canonical_root))
        is contained
    )


def test_other_windows_device_namespaces_are_not_rewritten() -> None:
    original: PureWindowsPath = PureWindowsPath(
        r"\\?\Volume{11111111-1111-1111-1111-111111111111}\files"
    )
    assert comparison_path(original) == original


def test_posix_canonical_paths_are_not_rewritten() -> None:
    original: PurePosixPath = PurePosixPath("/srv/files/version")
    assert comparison_path(original) is original
