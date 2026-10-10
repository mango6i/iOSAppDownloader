"""Search, history, purchase, and IPA streaming without invoking ipatool."""

import json
import os
import plistlib
import urllib.parse
from pathlib import Path

from .errors import NativeClientError, ProtocolError, TransportError
from .models import AppSummary, AppVersion, DownloadProduct, AppleAccount


CONFIGURATOR_UA = "Configurator/2.17 (Windows NT 10.0; Win64; x64) AppleWebKit/605.1.15"
PURCHASE_PATH = "/WebObjects/MZBuy.woa/wa/buyProduct"
DOWNLOAD_PATH = "/WebObjects/MZFinance.woa/wa/volumeStoreDownloadProduct"


def _find(value, key):
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for item in value.values():
            found = _find(item, key)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _find(item, key)
            if found is not None:
                return found
    return None


class AppleStoreClient:
    def __init__(self, transport, account=None, guid=""):
        self.transport = transport
        self.account = account
        self.guid = str(guid)

    def search_apps(self, keyword, country="CN", limit=50):
        query = urllib.parse.urlencode(
            {"term": str(keyword), "country": str(country or "CN").upper(), "entity": "software", "limit": int(limit)}
        )
        body = self.transport.get_bytes("https://itunes.apple.com/search?" + query)
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProtocolError("App Store search returned invalid JSON") from exc
        result = []
        for item in data.get("results", []):
            result.append(
                AppSummary(
                    app_id=int(item.get("trackId") or 0),
                    name=str(item.get("trackName") or ""),
                    bundle_id=str(item.get("bundleId") or ""),
                    version=str(item.get("version") or ""),
                    icon_url=str(item.get("artworkUrl512") or item.get("artworkUrl100") or ""),
                    store_url=str(item.get("trackViewUrl") or ""),
                    size=int(item.get("fileSizeBytes") or 0),
                    description=str(item.get("description") or ""),
                )
            )
        return result

    def fetch_public_history(self, app_id, base_url="https://apis.bilin.eu.org/history"):
        rows = []
        for page in range(1, 61):
            url = "%s/%s?page=%d" % (base_url.rstrip("/"), urllib.parse.quote(str(app_id)), page)
            data = json.loads(self.transport.get_bytes(url).decode("utf-8"))
            if data.get("code") != 200 or not data.get("data"):
                break
            for item in data["data"]:
                ext = str(item.get("external_identifier") or "").strip()
                ver = str(item.get("bundle_version") or "").strip()
                if ext and ver:
                    rows.append(
                        AppVersion(
                            version=ver,
                            external_id=ext,
                            date=str(item.get("created_at") or "")[:19].replace("T", " "),
                            size=int(item.get("size") or 0),
                        )
                    )
            if data.get("total") and len(rows) >= int(data["total"]):
                break
        return rows

    def list_versions(self, app_id):
        """Return Apple's official external version identifiers."""
        body = plistlib.dumps(
            {
                "salableAdamId": str(app_id),
                "guid": self.guid,
                "creditDisplay": "",
            },
            fmt=plistlib.FMT_XML,
            sort_keys=False,
        )
        errors = []
        for host in self._hosts():
            response = self.transport.request(
                "POST",
                host + DOWNLOAD_PATH + "?guid=" + urllib.parse.quote(self.guid),
                body,
                dict(self._headers(), **{"Content-Type": "application/x-apple-plist"}),
            )
            if not (200 <= response.status < 300) or not response.body:
                errors.append("%s: HTTP %d" % (host, response.status))
                continue
            try:
                values = plistlib.loads(response.body)
            except Exception:
                errors.append("%s: invalid plist" % host)
                continue
            failure = _find(values, "failureType")
            song_list = values.get("songList") if isinstance(values, dict) else None
            if failure and str(failure) not in ("", "5002"):
                errors.append("%s: %s" % (host, _find(values, "customerMessage") or failure))
                continue
            if isinstance(song_list, dict):
                return [str(value) for value in song_list.keys()]
            if not isinstance(song_list, list) or not song_list:
                errors.append("%s: missing songList" % host)
                continue
            item = song_list[0] if isinstance(song_list[0], dict) else {}
            metadata = item.get("metadata") if isinstance(item, dict) else None
            metadata = metadata if isinstance(metadata, dict) else item
            identifiers = metadata.get("softwareVersionExternalIdentifiers")
            if identifiers is None:
                identifiers = metadata.get("externalVersionIdentifiers")
            if not isinstance(identifiers, list):
                errors.append("%s: missing version identifiers" % host)
                continue
            return [str(value) for value in identifiers if isinstance(value, (str, int))]
        raise NativeClientError("version list unavailable: " + "; ".join(errors[:3]))

    def _require_account(self):
        if not isinstance(self.account, AppleAccount) or not self.account.valid:
            raise NativeClientError("a valid Apple account session is required")

    def _hosts(self):
        self._require_account()
        hosts = []
        if self.account.pod.isdigit():
            hosts.append("https://p%s-buy.itunes.apple.com" % self.account.pod)
        hosts.append("https://buy.itunes.apple.com")
        for number in range(1, 6):
            value = "https://p%d-buy.itunes.apple.com" % number
            if value not in hosts:
                hosts.append(value)
        return hosts

    def _headers(self):
        self._require_account()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": CONFIGURATOR_UA,
            "iCloud-DSID": self.account.dsid,
            "X-Dsid": self.account.dsid,
        }
        if self.account.password_token:
            headers["X-Token"] = self.account.password_token
        if self.account.storefront:
            headers["X-Apple-Store-Front"] = self.account.storefront
        return headers

    def purchase(self, app_id):
        body = plistlib.dumps(
            {
                "appExtVrsId": "0",
                "hasAskedToFulfillPreorder": "true",
                "hasDoneAgeCheck": "true",
                "buyWithoutAuthorization": "true",
                "hasBeenAuthedForBuy": "true",
                "guid": self.guid,
                "needDiv": "0",
                "origPage": "Software-%s" % app_id,
                "origPageLocation": "Buy",
                "price": "0",
                "pricingParameters": "STDQ",
                "productType": "C",
                "salableAdamId": str(app_id),
            },
            fmt=plistlib.FMT_XML,
            sort_keys=False,
        )
        last = ""
        for host in self._hosts():
            response = self.transport.request(
                "POST",
                host + PURCHASE_PATH,
                body,
                dict(self._headers(), **{"Content-Type": "application/x-apple-plist"}),
            )
            if 200 <= response.status < 300 and response.body:
                return response.body
            last = "HTTP %d" % response.status
        raise TransportError("purchase failed: " + last)

    def resolve_download(self, app_id, external_version_id):
        body = urllib.parse.urlencode(
            {
                "creditDisplay": "",
                "guid": self.guid,
                "salableAdamId": str(app_id),
                "appExtVrsId": str(external_version_id),
            }
        ).encode("utf-8")
        errors = []
        for host in self._hosts():
            response = self.transport.request("POST", host + DOWNLOAD_PATH + "?guid=" + urllib.parse.quote(self.guid), body, self._headers())
            if not (200 <= response.status < 300) or not response.body:
                errors.append("%s: HTTP %d" % (host, response.status))
                continue
            try:
                values = plistlib.loads(response.body)
            except Exception:
                errors.append("%s: invalid plist" % host)
                continue
            failure = _find(values, "failureType")
            if failure:
                errors.append("%s: %s" % (host, _find(values, "customerMessage") or failure))
                continue
            ipa_url = _find(values, "software-package")
            if not ipa_url:
                errors.append("%s: no IPA URL" % host)
                continue
            sinfs = _find(values, "sinfs") or []
            if not isinstance(sinfs, (list, tuple)):
                sinfs = [sinfs]
            return DownloadProduct(str(ipa_url), tuple(sinfs), _find(values, "metadata"))
        raise NativeClientError("download URL unavailable: " + "; ".join(errors[:3]))

    def download(self, product, destination, progress=None):
        parsed = urllib.parse.urlparse(product.ipa_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ProtocolError("IPA URL must be HTTPS")
        destination = Path(destination)
        temporary = destination.with_name(destination.name + ".part")
        written = 0
        try:
            # Control responses are buffered; IPA files use a dedicated stream
            # so a multi-gigabyte download is never copied into RAM first.
            with self.transport.open_stream(
                product.ipa_url,
                headers={"User-Agent": CONFIGURATOR_UA, "Accept": "*/*"},
                timeout=120,
            ) as source, open(temporary, "wb") as target:
                total = int(source.headers.get("Content-Length") or 0)
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, total)
            os.replace(temporary, destination)
            return destination
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
