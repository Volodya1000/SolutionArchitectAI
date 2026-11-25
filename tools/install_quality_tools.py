"""Install pinned, checksum-verified repository tools into ignored local scratch."""
import hashlib
import io
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

RELEASES = {
    "actionlint": ("rhysd/actionlint", "v1.7.12", {
        "Windows": ("actionlint_1.7.12_windows_amd64.zip", "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9"),
        "Linux": ("actionlint_1.7.12_linux_amd64.tar.gz", "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"),
    }),
    "typos": ("crate-ci/typos", "v1.52.2", {
        "Windows": ("typos-v1.52.2-x86_64-pc-windows-msvc.zip", "ab79036832cea0f2a21aa947731d39512250cc0f7a6a2f6add26262738a8cc11"),
        "Linux": ("typos-v1.52.2-x86_64-unknown-linux-musl.tar.gz", "3b13d1291281d39d01822e54035636487a7a0f228e70097899b1e33aeb0e7e93"),
    }),
}


def install(name: str) -> Path:
    repository, version, releases = RELEASES[name]
    system = platform.system()
    archive, digest = releases[system]
    directory = Path(__file__).resolve().parents[1] / ".build/quality-tools" / name
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / (name + (".exe" if system == "Windows" else ""))
    url = f"https://github.com/{repository}/releases/download/{version}/{archive}"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Quality tool checksum mismatch")
    if archive.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            binary.write_bytes(package.read(binary.name))
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as package:
            member = next(item for item in package.getmembers() if Path(item.name).name == name)
            stream = package.extractfile(member)
            if stream is None:
                raise ValueError("Missing tool binary")
            with stream:
                binary.write_bytes(stream.read())
        binary.chmod(0o755)
    return binary


if __name__ == "__main__":
    for tool in RELEASES:
        print(install(tool))
