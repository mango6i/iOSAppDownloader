"""Small protocol data models.  Secrets are excluded from repr output."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SapConfig:
    setup_url: str
    certificate_url: str
    version: int


@dataclass(frozen=True)
class BagConfig:
    authenticate_url: str
    sap: SapConfig
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class AppleAccount:
    email: str
    dsid: str
    password_token: str = field(default="", repr=False)
    storefront: str = ""
    pod: str = ""
    name: str = ""

    @property
    def valid(self):
        return self.dsid.isdigit() and len(self.dsid) >= 6 and bool(self.password_token)


@dataclass(frozen=True)
class AppSummary:
    app_id: int
    name: str
    bundle_id: str
    version: str = ""
    icon_url: str = ""
    store_url: str = ""
    size: int = 0
    description: str = ""


@dataclass(frozen=True)
class AppVersion:
    version: str
    external_id: str
    date: str = ""
    size: int = 0


@dataclass(frozen=True)
class DownloadProduct:
    ipa_url: str
    sinfs: tuple = ()
    metadata: Optional[Dict[str, Any]] = None
