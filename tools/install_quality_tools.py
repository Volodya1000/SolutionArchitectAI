"""Install pinned, checksum-verified repository tools into ignored local scratch."""

import hashlib
import io
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import IO, BinaryIO, Final

RELEASES: Final[dict[str, tuple[str, str, dict[str, tuple[str, str]]]]] = {
    "actionlint": (
        "rhysd/actionlint",
        "v1.7.12",
        {
            "Windows": (
                "actionlint_1.7.12_windows_amd64.zip",
                "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9",
            ),
            "Linux": (
                "actionlint_1.7.12_linux_amd64.tar.gz",
                "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
            ),
        },
    ),
    "typos": (
        "crate-ci/typos",
        "v1.52.2",
        {
            "Windows": (
                "typos-v1.52.2-x86_64-pc-windows-msvc.zip",
                "ab79036832cea0f2a21aa947731d39512250cc0f7a6a2f6add26262738a8cc11",
            ),
            "Linux": (
                "typos-v1.52.2-x86_64-unknown-linux-musl.tar.gz",
                "3b13d1291281d39d01822e54035636487a7a0f228e70097899b1e33aeb0e7e93",
            ),
        },
    ),
}


def install(name: str) -> Path:
    repository: str
    version: str
    releases: dict[str, tuple[str, str]]
    repository, version, releases = RELEASES[name]
    system: str = platform.system()
    archive: str
    digest: str
    archive, digest = releases[system]
    directory: Path = Path(__file__).resolve().parents[1] / ".build/quality-tools" / name
    directory.mkdir(parents=True, exist_ok=True)
    binary: Path = directory / (name + (".exe" if system == "Windows" else ""))
    url: str = f"https://github.com/{repository}/releases/download/{version}/{archive}"

    response: BinaryIO
    with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310
        data: bytes = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Quality tool checksum mismatch")
    write_binary(binary, data, zipped=archive.endswith(".zip"))
    return binary


def write_binary(binary: Path, data: bytes, *, zipped: bool) -> None:
    if zipped:
        zip_package: zipfile.ZipFile
        with zipfile.ZipFile(io.BytesIO(data)) as zip_package:
            binary.write_bytes(zip_package.read(binary.name))
        return
    package: tarfile.TarFile
    with tarfile.open(fileobj=io.BytesIO(data)) as package:
        member: tarfile.TarInfo = next(
            item for item in package.getmembers() if Path(item.name).name == binary.name
        )
        stream: IO[bytes] | None = package.extractfile(member)
        if stream is None:
            raise ValueError("Missing tool binary")
        with stream:
            binary.write_bytes(stream.read())
    binary.chmod(0o755)


def main() -> None:
    tool: str
    for tool in RELEASES:
        print(install(tool))


if __name__ == "__main__":
    main()
