"""Apple bag discovery and endpoint validation."""

import plistlib
import urllib.parse

from .errors import ProtocolError
from .models import BagConfig, SapConfig


BAG_URL = "https://init.itunes.apple.com/bag.xml?ix=5"
SUPPORTED_SAP_VERSION = 200
AUTH_PATH = "/WebObjects/MZFinance.woa/wa/authenticate"
NATIVE_FAST_HOST = "auth.itunes.apple.com"


def _url(value, key):
    value = str(value or "").strip()
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception as exc:
        raise ProtocolError("bag: invalid %s URL" % key) from exc
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProtocolError("bag: %s must be an absolute HTTPS URL" % key)
    return value


def validate_auth_endpoint(url):
    parsed = urllib.parse.urlparse(str(url))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ProtocolError("authentication endpoint is not HTTPS")
    path = parsed.path.rstrip("/") or "/"
    # Apple 依据 User-Agent 返回不同的认证端点：iTunes 标识下是
    # /auth/v1/native，Configurator 标识下是 /auth/v1/native/fast。
    # 两者都是有效的认证端点，必须同时接受，否则会被误判为非法端点。
    native_fast = host == NATIVE_FAST_HOST and path in (
        "/auth/v1/native/fast", "/auth/v1/native")
    legacy_host = host == "buy.itunes.apple.com" or host.endswith("-buy.itunes.apple.com")
    legacy = legacy_host and path == AUTH_PATH
    if not native_fast and not legacy:
        raise ProtocolError("authentication endpoint has an unexpected host or path")
    return str(url)


def _decode_outer(document):
    try:
        outer = plistlib.loads(document)
    except Exception as exc:
        raise ProtocolError("bag response is not a valid plist") from exc
    if not isinstance(outer, dict):
        raise ProtocolError("bag response root is not a dictionary")
    inner = outer.get("bag")
    if isinstance(inner, bytes):
        try:
            inner = plistlib.loads(inner)
        except Exception as exc:
            raise ProtocolError("bag data is not a valid inner plist") from exc
    if not isinstance(inner, dict):
        # A few test/staging responses expose the inner values directly.
        inner = outer
    return inner


def parse_bag(document_or_mapping):
    inner = (
        _decode_outer(document_or_mapping)
        if isinstance(document_or_mapping, (bytes, bytearray))
        else document_or_mapping
    )
    if not isinstance(inner, dict):
        raise ProtocolError("bag is not a dictionary")
    auth = validate_auth_endpoint(_url(inner.get("authenticateAccount"), "authenticateAccount"))
    try:
        version = int(str(inner.get("sign-sap-version", "")).strip())
    except ValueError as exc:
        raise ProtocolError("bag: invalid sign-sap-version") from exc
    sap = SapConfig(
        setup_url=_url(inner.get("sign-sap-setup"), "sign-sap-setup"),
        certificate_url=_url(inner.get("sign-sap-setup-cert"), "sign-sap-setup-cert"),
        version=version,
    )
    if sap.version != SUPPORTED_SAP_VERSION:
        raise ProtocolError(
            "unsupported SAP version %d (expected %d)" % (sap.version, SUPPORTED_SAP_VERSION)
        )
    return BagConfig(authenticate_url=auth, sap=sap, raw=dict(inner))


def fetch_bag(transport, url=BAG_URL):
    return parse_bag(transport.get_bytes(url, timeout=30))
