"""Windows adapter for the official majd/ipatool CLI (no Python SAP runtime)."""
import ctypes
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time

from prepare_engine import VERSION as ENGINE_VERSION

# Optional local seeds must match the modern framework profile pinned by 2.8.1.
# Never copy the incompatible 2.7 CommerceKit/CoreFP profile into the new cache.
SEED_FILES = {
    **{f"apple-assets/{name}": (f"ipatool/sap/apple-assets-macos-27-26A434-arm64-v5/{name}", digest)
       for name, digest in {
           "AppleMediaServices": "95f4558aa2c0ccd9f96ed479e336b630b46bf4b4e0baabc1c1ac8c7d55e21ab4",
           "commerce": "c4b2088dd39aeb353f59cb57597902e8317aec66ae7da0414b03c5f932771343",
           "adid": "43419a206c28bc93ecb8884256088d18306a0a462350f83adbced8e60a94e390",
           "CoreFP": "afbc123e688a822d980d5816cc2b52f69fde669d1dca92cf85627e1cbee587f6",
           "CoreFP.icxs": "cb8f55330ec567da3e692dab5f5388bed0312dd9093340477c5759078cc2aa7b",
           "fairplayd": "1e58d37e9602dd0ca5e24b14762063b6c310248b4d3a94272771d815e4ea1784",
           "FairPlayIOKit": "47452960ec010d3a80b02cceec73a65f8a9758850fd0fb7b2fdac7a5d1b81025",
       }.items()},
    "unicorn-2.1.4/libunicorn.dll": ("ipatool/unicorn/2.1.4/libunicorn.dll", "d8f9a89222ffa74493a1d47090e17f8e1db8ac171a3128c6a76a4ea09de11469"),
}


def json_records(text):
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text or ""):
        starts = [i for i in (text.find("{", pos), text.find("[", pos)) if i >= 0]
        if not starts:
            break
        start = min(starts)
        try:
            record, end = decoder.raw_decode(text, start)
        except ValueError:
            pos = start + 1
            continue
        yield record
        pos = end


def auth_result(rc, out):
    """Exit 0 with a 2FA prompt is NOT a successful login in upstream CLI."""
    needs_code, identity, success = False, "", False
    markers = ("2fa code is required", "auth code is required", "auth_code_required",
               "authcoderequired", "two_factor_required", "try a fresh 2fa code")
    records = [record for record in json_records(out or "") if isinstance(record, dict)]
    for record in records:
        message = " ".join(str(record.get(k, "")) for k in ("message", "error", "code")).lower()
        needs_code |= any(marker in message for marker in markers)
        if record.get("success") is False:
            success, identity = False, ""
        elif record.get("success") is True and (record.get("email") or record.get("name")):
            success = True
            identity = str(record.get("email") or record["name"]).strip()
    if not records:
        needs_code = any(marker in (out or "").lower() for marker in markers)
    if rc == 0 and success:
        return True, False, identity
    return False, bool(needs_code), identity


@lru_cache(maxsize=1)
def storefront_country_codes():
    """Shared with the Go engine; IDs identify regions, not account rights."""
    path = Path(__file__).resolve().parent / "ipatool" / "compat" / "storefronts.json"
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict) or not values:
        raise ValueError("Bundled storefront mapping is missing or invalid")
    for code, identifier in values.items():
        if not re.fullmatch(r"[A-Z]{2}", code) or not re.fullmatch(r"[0-9]{6}", identifier):
            raise ValueError("Invalid bundled storefront mapping")
    return {identifier: code.lower() for code, identifier in values.items()}


def account_country(rc, out):
    """Read verified account metadata; never guess from IP/email/GUI settings."""
    if not auth_result(rc, out)[0]:
        return ""
    for record in reversed(list(json_records(out or ""))):
        if not isinstance(record, dict) or record.get("success") is not True:
            continue
        storefront = str(record.get("storeFront") or "").strip()
        identifier = re.split(r"[-,]", storefront, maxsplit=1)[0]
        mapped = storefront_country_codes().get(identifier, "")
        code = str(record.get("countryCode") or "").strip().lower()
        if not re.fullmatch(r"[a-z]{2}", code):
            code = ""
        if code and mapped and code != mapped:
            return ""  # Conflicting metadata must not silently switch regions.
        return mapped or code
    return ""


def version_rows(out):
    """Map the official numeric ID list without inventing display versions."""
    ids = []
    for record in json_records(out or ""):
        if isinstance(record, dict) and record.get("success") is True:
            value = record.get("externalVersionIdentifiers")
            if isinstance(value, list):
                ids = [str(item).strip() for item in value if not isinstance(item, bool)]
    valid = {value for value in ids if value.isascii() and value.isdigit() and int(value) > 0}
    return [{"version": "", "external_id": value, "date": "", "size": 0}
            for value in sorted(valid, key=int, reverse=True)]


def redact_output(out, secrets=()):
    value = out or ""
    for secret in sorted((str(s) for s in secrets if s), key=len, reverse=True):
        # Match both raw and JSON-escaped command arguments.
        value = value.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "***")
        value = value.replace(secret, "***")
    return re.sub(
        r'("(?:password|password_token|passwordToken|directory_services_id|directoryServicesID|'
        r'dsid|authCode|auth_code|token|cookies?|authorization)"\s*:\s*)'
        r'(?:"(?:[^"\\]|\\.)*"|\d+)', r'\1"***"', value, flags=re.IGNORECASE)


def hidden_process_flags():
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


def process_is_running(pid):
    """A read-only PID check; never use os.kill(pid, 0) on Windows."""
    if pid == os.getpid():
        return True
    if not 0 < pid <= 0xFFFFFFFF:
        return True
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Access denied and unknown errors are not proof that a process died.
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def path_is_link(path):
    # FILE_ATTRIBUTE_REPARSE_POINT also covers Windows junctions on Python
    # versions without pathlib.Path.is_junction().
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


class EngineSession:
    """Per-run credentials, persistent non-secret assets, cancellable children."""
    def __init__(self, data_root, seed_root="", frozen_root=""):
        self.root = Path(data_root).resolve()
        self.sessions = self.root / "sessions"
        self.sessions.mkdir(parents=True, exist_ok=True)
        self._clear_stale_sessions()
        self.home = Path(tempfile.mkdtemp(prefix="run-%s-" % os.getpid(), dir=self.sessions))
        self.cache = self.root / "engine-cache"
        self.seed_root = Path(seed_root) if seed_root else None
        self.frozen_root = os.path.normcase(os.path.abspath(frozen_root)) if frozen_root else ""
        self.passphrase = os.urandom(32).hex()
        self._prepare_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._spawn_lock = threading.Lock()
        self._processes = set()
        self._seeded = False
        self._closed = False

    def _clear_stale_sessions(self):
        # Remove only our dead-process account directories. Never follow links,
        # remove another running instance, or touch the persistent asset cache.
        for candidate in self.sessions.iterdir():
            match = re.fullmatch(r"run-([1-9][0-9]*)-[a-zA-Z0-9_-]+", candidate.name)
            if not match or path_is_link(candidate):
                continue
            if candidate.resolve().parent != self.sessions.resolve() or not candidate.is_dir():
                continue
            if process_is_running(int(match.group(1))):
                continue
            try:
                shutil.rmtree(candidate)
            except OSError:
                pass  # Locked leftovers can be retried at the next launch.

    def prepare(self):
        with self._prepare_lock:
            if self._closed:
                raise RuntimeError("Authentication component is shutting down")
            self.home.mkdir(parents=True, exist_ok=True)
            self.cache.mkdir(parents=True, exist_ok=True)
            if self._seeded:
                return
            if self.seed_root:
                source_root = self.seed_root / ".ipatool" / "cache"
                for source, (target, digest) in SEED_FILES.items():
                    src, dst = source_root / source, self.cache / target
                    if not src.is_file():
                        continue
                    if dst.is_file() and hashlib.sha256(dst.read_bytes()).hexdigest() == digest:
                        continue
                    if hashlib.sha256(src.read_bytes()).hexdigest() != digest:
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    temporary = dst.with_name(dst.name + ".seed-%s" % os.getpid())
                    shutil.copy2(src, temporary)
                    os.replace(temporary, dst)
            self._seeded = True

    def environment(self, proxy=""):
        self.prepare()
        env = os.environ.copy()
        # Upstream Windows HomeDirectory uses HOMEDRIVE+HOMEPATH, not HOME.
        drive, tail = os.path.splitdrive(str(self.home))
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), HOMEDRIVE=drive,
                   HOMEPATH=tail, APPDATA=str(self.home / "roaming"),
                   XDG_STATE_HOME=str(self.home / "state"),
                   XDG_DATA_HOME=str(self.home / "data"),
                   LOCALAPPDATA=str(self.cache), XDG_CACHE_HOME=str(self.cache))
        for key in list(env):
            if key.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy") or key.startswith("IPATOOL_"):
                env.pop(key, None)
        if proxy:
            env.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy, http_proxy=proxy, https_proxy=proxy)
        if self.frozen_root:
            env["PATH"] = os.pathsep.join(
                item for item in env.get("PATH", "").split(os.pathsep)
                if item and not os.path.normcase(os.path.abspath(item)).startswith(self.frozen_root + os.sep)
                and os.path.normcase(os.path.abspath(item)) != self.frozen_root)
            for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONHOME", "PYTHONPATH"):
                env.pop(key, None)
        return env

    def command(self, executable, args):
        return [str(executable), "--keychain-passphrase", self.passphrase, *args]

    def launch(self, command, **kwargs):
        # PyInstaller's process-wide DLL search directory is inherited by children.
        # Clear only during CreateProcess and immediately restore it for Qt.
        with self._spawn_lock:
            if self._closed:
                raise RuntimeError("Authentication component is shutting down")
            old = None
            if os.name == "nt" and self.frozen_root:
                buffer = ctypes.create_unicode_buffer(32768)
                ctypes.windll.kernel32.GetDllDirectoryW(len(buffer), buffer)
                old = buffer.value
                ctypes.windll.kernel32.SetDllDirectoryW(None)
            try:
                proc = subprocess.Popen(command, **hidden_process_flags(), **kwargs)
            finally:
                if old is not None:
                    ctypes.windll.kernel32.SetDllDirectoryW(old or None)
            with self._process_lock:
                self._processes = {p for p in self._processes if p.poll() is None}
                self._processes.add(proc)
        return proc

    def execute(self, command, env, timeout, cancel=None, on_output=None):
        if cancel and cancel.is_set():
            return -4, "login cancelled"
        proc = self.launch(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        deadline = time.monotonic() + timeout
        output_queue = queue.Queue()
        output = []

        def read_output():
            # On Windows communicate(timeout) does not expose partial output.
            # Read on a separate thread so JSON messages arrive before exit,
            # while the calling thread can still cancel a silent CLI.
            try:
                for line in proc.stdout:
                    output_queue.put(("line", line))
            except Exception as exc:
                output_queue.put(("error", exc))
            finally:
                output_queue.put(("end", None))

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        ended = False
        try:
            while True:
                cancelled = cancel and cancel.is_set()
                remaining = deadline - time.monotonic()
                if cancelled or remaining <= 0:
                    return (-4, "login cancelled") if cancelled else (-2, "timeout after %ss" % timeout)
                if ended and proc.poll() is not None:
                    return proc.returncode, "".join(output)
                try:
                    kind, value = output_queue.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue
                if kind == "error":
                    raise value
                if kind == "end":
                    ended = True
                else:
                    output.append(value)
                    if on_output and value.strip():
                        on_output(value.rstrip("\r\n"))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            reader.join(timeout=5)
            proc.stdout.close()
            with self._process_lock:
                self._processes.discard(proc)

    def terminate_all(self):
        with self._spawn_lock:
            self._closed = True
            with self._process_lock:
                processes = list(self._processes)
        for proc in processes:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def clear_credentials(self):
        # This exact generated directory is ours. Never delete a user's .ipatool.
        if self.home.parent.resolve() != self.sessions.resolve() or not self.home.name.startswith("run-"):
            raise RuntimeError("Refusing to remove an unexpected session directory")
        if path_is_link(self.home):
            raise RuntimeError("Refusing to remove a linked session directory")
        with self._prepare_lock:
            if self.home.exists():
                shutil.rmtree(self.home)

