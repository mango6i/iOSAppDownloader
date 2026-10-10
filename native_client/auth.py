"""Independent Apple ID authentication state machine."""

import base64
import plistlib
import re
import urllib.parse
from dataclasses import dataclass

from .bag import validate_auth_endpoint
from .errors import (
    AuthenticationRejected,
    LoginIncomplete,
    ProtocolError,
    SapRequiredError,
    TwoFactorRequired,
)
from .models import AppleAccount, BagConfig


ACTION_SIGNATURE_HEADER = "X-Apple-ActionSignature"
MAX_ATTEMPTS = 4
LEGACY_AUTHENTICATE_URL = (
    "https://buy.itunes.apple.com/WebObjects/MZFinance.woa/wa/authenticate"
)


def build_auth_plist(email, password, guid, attempt=1, verification_code=None):
    secret = str(password)
    if verification_code:
        secret += str(verification_code).strip()
    values = {
        "appleId": str(email),
        "attempt": str(int(attempt)),
        "guid": str(guid),
        "password": secret,
        "rmp": "0",
        "why": "signIn",
    }
    return plistlib.dumps(values, fmt=plistlib.FMT_XML, sort_keys=False)


def _signed_payload(url, body):
    """Apple 的 ActionSignature 覆盖「请求路径 + 请求体」。

    只对 body 签名时，Apple 会返回 customerMessage=AMD-Action:<path>:SP，
    即签名校验未通过；把请求路径一并计入后即可通过校验。
    """
    path = urllib.parse.urlparse(str(url)).path or "/"
    return path.encode("utf-8") + bytes(body)


def _walk_values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
            yield from _walk_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_values(item)


def _first(values, keys):
    for key, value in _walk_values(values):
        if key in keys and value not in (None, "", b""):
            return value
    return None


def _string(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _requires_code(values):
    markers = []
    for key, value in _walk_values(values):
        text = (key + " " + _string(value)).lower()
        markers.append(text)
    blob = " ".join(markers)
    return any(
        marker in blob
        for marker in (
            "authcoderequired",
            "verificationcoderequired",
            "two-factor",
            "two factor",
            "trusted device",
            "enter verification code",
        )
    )


def _error_message(values):
    value = _first(
        values,
        {
            "customerMessage",
            "errorMessage",
            "failureReason",
            "localizedFailureReason",
            "message",
        },
    )
    return _string(value).strip()


def _parse_account(values, email, response):
    token = _string(_first(values, {"passwordToken", "password-token"})).strip()
    dsid = _string(_first(values, {"dsPersonId", "dsid", "directoryServicesId"})).strip()
    if not token or not dsid:
        raise ProtocolError("authentication response is missing account identifiers")
    account_info = _first(values, {"accountInfo"}) or {}
    address = account_info.get("address", {}) if isinstance(account_info, dict) else {}
    name = "%s %s" % (_string(address.get("firstName")), _string(address.get("lastName")))
    name = name.strip()
    return AppleAccount(
        email=str(email),
        dsid=dsid,
        password_token=token,
        storefront=_string(response.header("x-set-apple-store-front", "")).strip(),
        pod=_string(response.header("pod", "")).strip(),
        name=name,
    )


@dataclass
class LoginChallenge:
    """A pending login that keeps the same session and SAP signer for code entry."""

    authenticator: object
    email: str
    password: str
    bag: BagConfig
    signer: object
    guid: str
    attempt: int = 1

    def submit(self, code):
        code = str(code or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            raise AuthenticationRejected("verification code must contain exactly six digits")
        return self.authenticator._submit(
            self.email,
            self.password,
            self.bag,
            self.signer,
            self.guid,
            self.attempt + 1,
            code,
        )


class AppleAuthenticator:
    def __init__(self, transport, guid, bag=None):
        self.transport = transport
        self.guid = str(guid)
        self.bag = bag

    def login(self, email, password, signer=None, code_provider=None):
        if signer is None:
            raise SapRequiredError(
                "Apple login now requires an SAP action signature; no unsigned fallback is attempted"
            )
        bag = self.bag
        if bag is None:
            raise ProtocolError("a parsed Apple bag is required before login")
        pending = self._submit(email, password, bag, signer, self.guid, 1, None)
        if isinstance(pending, LoginChallenge):
            if code_provider is None:
                raise pending
            return pending.submit(code_provider(pending))
        return pending

    def _submit(self, email, password, bag, signer, guid, attempt, code):
        validate_auth_endpoint(bag.authenticate_url)
        body = build_auth_plist(email, password, guid, attempt=attempt, verification_code=code)
        endpoints = [_with_guid(bag.authenticate_url, guid)]
        # Apple's current bag frequently advertises native/fast while the
        # edge returns an empty 204/301. Retry the same signed request against
        # the legacy MZFinance endpoint, which is still the real account
        # backend and can return the normal plist/2FA response.
        if urllib.parse.urlparse(bag.authenticate_url).hostname == "auth.itunes.apple.com":
            endpoints.append(_with_guid(LEGACY_AUTHENTICATE_URL, guid))
        response = None
        for endpoint in endpoints:
            # 签名覆盖请求路径，因此每个端点都要单独签名。
            signature = signer.sign(_signed_payload(endpoint, body))
            headers = {
                "Content-Type": "application/x-apple-plist",
                ACTION_SIGNATURE_HEADER: signature,
            }
            response = self.transport.request_following_redirects(
                "POST",
                endpoint,
                body=body,
                headers=headers,
                max_redirects=5,
                validator=validate_auth_endpoint,
            )
            if response.body:
                break
        if response is None or not response.body:
            if response is not None and response.status == 403:
                raise SapRequiredError("Apple rejected the signed authentication request")
            status = response.status if response is not None else 0
            raise ProtocolError("Apple returned an empty authentication response (HTTP %d)" % status)
        try:
            values = plistlib.loads(response.body)
        except Exception as exc:
            raise ProtocolError("Apple authentication response is not a plist") from exc
        if not isinstance(values, dict):
            raise ProtocolError("Apple authentication response is not a dictionary")
        message = _error_message(values)
        if _requires_code(values):
            return LoginChallenge(self, str(email), str(password), bag, signer, str(guid), attempt)
        if message and not _first(values, {"passwordToken", "password-token"}):
            raise AuthenticationRejected(message)
        try:
            return _parse_account(values, email, response)
        except ProtocolError as exc:
            if message:
                raise AuthenticationRejected(message) from exc
            raise


def _with_guid(url, guid):
    """Add exactly one URL-encoded guid while preserving Apple's endpoint."""
    parsed = urllib.parse.urlsplit(str(url))
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
             if key.lower() != "guid"]
    query.append(("guid", str(guid)))
    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urllib.parse.urlencode(query),
        parsed.fragment,
    ))
