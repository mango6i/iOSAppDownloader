"""Independent in-process Apple Store client.

This package is deliberately separate from the stable desktop application.  It
does not launch, import, or depend on ``ipatool.exe``.  The public API is split
into transport, SAP setup, authentication, and Store operations so each layer
can be tested without putting an Apple ID on disk.
"""

from .auth import AppleAuthenticator, LoginChallenge, build_auth_plist
from .bag import fetch_bag, parse_bag, validate_auth_endpoint
from .errors import (
    AuthenticationError,
    AuthenticationRejected,
    LoginIncomplete,
    NativeClientError,
    SapRequiredError,
    TwoFactorRequired,
)
from .models import AppleAccount, BagConfig, SapConfig
from .sap import ActionSigner, SapMachine, SapSession
from .store import AppleStoreClient
from .transport import AppleTransport, HttpResponse

__all__ = [
    "ActionSigner",
    "AppleAccount",
    "AppleAuthenticator",
    "AppleStoreClient",
    "AppleTransport",
    "AuthenticationError",
    "AuthenticationRejected",
    "BagConfig",
    "HttpResponse",
    "LoginChallenge",
    "LoginIncomplete",
    "NativeClientError",
    "SapConfig",
    "SapMachine",
    "SapRequiredError",
    "SapSession",
    "TwoFactorRequired",
    "build_auth_plist",
    "fetch_bag",
    "parse_bag",
    "validate_auth_endpoint",
]
