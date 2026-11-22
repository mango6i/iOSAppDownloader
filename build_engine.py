"""Reproduce ipatool 2.8.1 with the app-private pinned Apple-root fix.

Build-time only: users of the packaged app do not need Go, Python, or a
certificate-store change. No authentication protocol is reimplemented here.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

SOURCE_URL = "https://codeload.github.com/majd/ipatool/tar.gz/refs/tags/v2.8.1"
SOURCE_SHA256 = "88704a28231ac0019016c1900edebc9dea0cf14de4e5bc90aa96fd594925bdc0"
GO_VERSION = "go1.27.4"
GO_ARCHIVE = GO_VERSION + ".windows-amd64.zip"
GO_SHA256 = "178ab98950ac69ab25069307dc6ade79f3816e414cce95b4da166a115cde1e7e"


def download_verified(url, target, digest, size_limit):
    request = urllib.request.Request(url, headers={"User-Agent": "iOSAppDownloader-source-build"})
    hasher = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as output:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > size_limit:
                raise ValueError("Build archive exceeds size limit")
            hasher.update(chunk)
            output.write(chunk)
    if hasher.hexdigest() != digest:
        raise ValueError("Build archive checksum mismatch")


def build(root, work, source_archive=None, go=None):
    root, work = Path(root).resolve(), Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    archive_path = Path(source_archive) if source_archive else work / "upstream.tar.gz"
    if source_archive is None:
        download_verified(SOURCE_URL, archive_path, SOURCE_SHA256, 64 * 1024 * 1024)
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Official source archive checksum mismatch")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            destination = (work / member.name).resolve()
            if not destination.is_relative_to(work) or not (member.isfile() or member.isdir()):
                raise ValueError("Unexpected source archive entry")
        archive.extractall(work, filter="data")
    source = work / "ipatool-2.8.1"
    for name in ("http_client.go", "http_client_compat_test.go"):
        shutil.copy2(root / "ipatool" / "compat" / name, source / "internal" / "storeauth" / name)
    for name in ("storefronts.json", "storefront_compat.go", "storefront_compat_test.go"):
        shutil.copy2(root / "ipatool" / "compat" / name, source / "pkg" / "appstore" / name)
    # Exact anchors fail closed if the pinned upstream changes. Keep upstream
    # dynamic discovery for unknown/new regions; known account IDs work offline.
    patches = {
        "pkg/appstore/appstore.go": (
            "\t\tkeychain:            args.Keychain,",
            "\t\tstorefrontCountryCodes: knownStorefrontCountryCodes(),\n\t\tkeychain:            args.Keychain,"),
        "cmd/auth.go": (
            '\t\t\t\tStr("email", output.Account.Email).',
            '\t\t\t\tStr("email", output.Account.Email).\n'
            '\t\t\t\tStr("storeFront", output.Account.StoreFront).\n'
            '\t\t\t\tStr("countryCode", appstore.StorefrontCountryCode(output.Account.StoreFront)).'),
    }
    for name, (before, after) in patches.items():
        path = source / name
        text = path.read_text(encoding="utf-8")
        expected = 2 if name == "cmd/auth.go" else 1
        if text.count(before) != expected:
            raise ValueError("Pinned upstream integration anchor changed: " + name)
        path.write_text(text.replace(before, after), encoding="utf-8", newline="\n")
    selected = str(go or shutil.which("go") or "")
    if not selected or subprocess.check_output([selected, "version"], text=True).strip() != "go version " + GO_VERSION + " windows/amd64":
        if go:
            raise RuntimeError("The compatibility build requires Go 1.27.4 windows/amd64")
        go_zip = work / GO_ARCHIVE
        download_verified("https://dl.google.com/go/" + GO_ARCHIVE, go_zip, GO_SHA256, 128 * 1024 * 1024)
        with zipfile.ZipFile(go_zip) as archive:
            for name in archive.namelist():
                if not (work / name).resolve().is_relative_to(work):
                    raise ValueError("Unexpected Go archive entry")
            archive.extractall(work)
        selected = str(work / "go" / "bin" / "go.exe")
    env = os.environ.copy()
    return _compile(selected, source, work, env)


def _compile(go, source, work, env):
    env.update(CGO_ENABLED="0", GOTOOLCHAIN="local", GOENV="off", GOWORK="off",
               GOOS="windows", GOARCH="amd64", GOAMD64="v1",
               GOCACHE=str(work / "go-cache"), GOMODCACHE=str(work / "go-modules"))
    # Do not enable the opt-in network test during ordinary builds.
    env.pop("IOSAPP_TLS_CHECK", None)
    subprocess.run([go, "test", "./internal/storeauth", "-run",
                    "TestPinnedAppleRootValidAndTampered|TestAppleRootInstallIsPrivateAndOffline", "-v"],
                   cwd=source, env=env, check=True, timeout=600)
    # Upstream source archives intentionally omit generated test mocks.
    subprocess.run([go, "generate", "./pkg/..."], cwd=source, env=env, check=True, timeout=600)
    subprocess.run([go, "test", "./pkg/appstore", "-run",
                    "TestKnownStorefrontsWorkOffline|TestProductionStorefrontSeedAndUnknownRegion", "-v"],
                   cwd=source, env=env, check=True, timeout=600)
    target = work / "ipatool-compatible.exe"
    subprocess.run([go, "build", "-trimpath", "-buildvcs=false", "-ldflags",
                    "-s -w -buildid= -X github.com/majd/ipatool/v2/cmd.version=2.8.1",
                    "-o", str(target), "."], cwd=source, env=env, check=True, timeout=600)
    return target
