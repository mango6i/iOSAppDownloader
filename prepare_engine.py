"""Prepare the unmodified official Windows engine for source builds."""
import argparse
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import urllib.request

VERSION = "2.7.0"
URL = f"https://github.com/majd/ipatool/releases/download/v{VERSION}/ipatool-{VERSION}-windows-amd64.tar.gz"
ARCHIVE_SHA256 = "b729608716908be287c2e6972f9e8cd05f879810ae5d182fc856c9e57cca0dd5"
EXE_SHA256 = "7b83589b74ad533f5d5dbab0ca87a5cb76b123bcbeb2553d57e9c154e35d8755"
MEMBER = f"bin/ipatool-{VERSION}-windows-amd64.exe"


def unpack_verified(data):
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Official engine archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = archive.getmember(MEMBER)
        if not member.isfile() or member.size > 64 * 1024 * 1024:
            raise ValueError("Unexpected engine archive entry")
        with archive.extractfile(member) as source:
            binary = source.read()
    if hashlib.sha256(binary).hexdigest() != EXE_SHA256:
        raise ValueError("Official engine executable checksum mismatch")
    return binary


def prepare(root, archive_path=None):
    target = Path(root) / "ipatool" / "majd" / "ipatool.exe"
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == EXE_SHA256:
        return target
    if archive_path is not None:
        data = Path(archive_path).read_bytes()
    else:
        request = urllib.request.Request(URL, headers={"User-Agent": "iOSAppDownloader-source-build"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024:
            raise ValueError("Engine archive exceeds the expected size limit")
    binary = unpack_verified(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as temporary:
        temporary.write(binary)
        staged = Path(temporary.name)
    try:
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use an already downloaded official archive")
    arguments = parser.parse_args()
    print(prepare(Path(__file__).resolve().parent, arguments.archive))
