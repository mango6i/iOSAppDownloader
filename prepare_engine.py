"""Prepare ipatool 2.8.1 with a reproducible app-private Apple-root fix."""
import argparse
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile

VERSION = "2.8.1"
URL = f"https://github.com/majd/ipatool/releases/download/v{VERSION}/ipatool-{VERSION}-windows-amd64.tar.gz"
ARCHIVE_SHA256 = "a8ccd8075bc083f99caa49976997860ba5e0e3e8f76b450360cd805262542e97"
EXE_SHA256 = "6acffaf80309ffa920ccf89d4413eba6295e397fe9c38924d1176ea0a252171a"
UPSTREAM_EXE_SHA256 = "1c8145d4b39ff993ebce7cf832d5504ed563cc1526bb21ef5cef27d28aceb2dd"
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
    if hashlib.sha256(binary).hexdigest() != UPSTREAM_EXE_SHA256:
        raise ValueError("Official engine executable checksum mismatch")
    return binary


def prepare(root, archive_path=None, go=None):
    target = Path(root) / "ipatool" / "majd" / "ipatool.exe"
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == EXE_SHA256:
        return target
    from build_engine import build
    with tempfile.TemporaryDirectory(prefix="iosapp-engine-build-") as workspace:
        built = build(root, workspace, source_archive=archive_path, go=go)
        binary = built.read_bytes()
    actual_digest = hashlib.sha256(binary).hexdigest()
    if actual_digest != EXE_SHA256:
        raise ValueError("Compatible engine executable checksum mismatch: expected "
                         + EXE_SHA256 + ", got " + actual_digest)
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
    parser.add_argument("--archive", type=Path, help="Use the pinned upstream source archive")
    parser.add_argument("--go", type=Path, help="Use an existing Go 1.27.4 executable (build-time only)")
    arguments = parser.parse_args()
    print(prepare(Path(__file__).resolve().parent, arguments.archive, arguments.go))
