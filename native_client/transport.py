"""Cookie-preserving HTTPS transport with safe POST redirect handling."""

import http.cookiejar
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .errors import TransportError


# Apple 的边缘节点会按 User-Agent 拒绝请求：使用 Configurator 标识时
# authenticate 端点直接返回 403（空响应体），换成 iTunes 标识后同一份
# 签名与请求体即可拿到 200 + 正常 plist 业务响应。
USER_AGENT = (
    "iTunes/12.12.7 (Windows; Microsoft Windows 10 x64; x64) "
    "AppleWebKit/537.36"
)
_REDIRECT_CODES = frozenset((301, 302, 303, 307, 308))


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: object
    body: bytes
    url: str

    @property
    def redirected(self):
        return self.status in _REDIRECT_CODES

    def header(self, name, default=None):
        return self.headers.get(name, default)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Surface redirects so an auth POST can be replayed with its body."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_ssl_context():
    return ssl.create_default_context()


class AppleTransport:
    """A short-lived Apple session held entirely in memory by default."""

    def __init__(self, proxy=None, timeout=30, user_agent=USER_AGENT):
        self.timeout = int(timeout)
        self.user_agent = str(user_agent)
        self.cookies = http.cookiejar.CookieJar()
        if proxy is None:
            proxy_handler = urllib.request.ProxyHandler()
        elif str(proxy).strip():
            value = str(proxy).strip()
            proxy_handler = urllib.request.ProxyHandler({"http": value, "https": value})
        else:
            proxy_handler = urllib.request.ProxyHandler({})
        self._opener = urllib.request.build_opener(
            proxy_handler,
            urllib.request.HTTPCookieProcessor(self.cookies),
            _NoRedirectHandler(),
        )
        self._ssl_context = _build_ssl_context()

    def clear(self):
        for cookie in list(self.cookies):
            self.cookies.clear(cookie.domain, cookie.path, cookie.name)

    def request(self, method, url, body=None, headers=None, timeout=None):
        method = str(method or "GET").upper()
        url = str(url)
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Connection": "close",
        }
        if headers:
            request_headers.update({str(k): str(v) for k, v in headers.items()})
        data = body
        if data is not None and not isinstance(data, bytes):
            data = bytes(data)
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with self._opener.open(request, timeout=timeout or self.timeout, context=self._ssl_context) as response:
                return HttpResponse(
                    status=int(response.status),
                    headers=response.headers,
                    body=response.read(),
                    url=response.geturl(),
                )
        except TypeError:
            # Some Python builds do not accept context when an opener already
            # has an HTTPS handler.  The default verified context remains in
            # force through the opener's HTTPS handler.
            try:
                with self._opener.open(request, timeout=timeout or self.timeout) as response:
                    return HttpResponse(
                        status=int(response.status),
                        headers=response.headers,
                        body=response.read(),
                        url=response.geturl(),
                    )
            except urllib.error.HTTPError as exc:
                return HttpResponse(exc.code, exc.headers, exc.read(), url)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise TransportError("%s %s: %s" % (method, url, exc)) from exc
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, exc.headers, exc.read(), url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError("%s %s: %s" % (method, url, exc)) from exc

    def request_following_redirects(self, method, url, body=None, headers=None, max_redirects=5, validator=None):
        """Follow redirects without changing a POST into a bodyless GET."""
        current = str(url)
        response = None
        for _ in range(int(max_redirects) + 1):
            response = self.request(method, current, body=body, headers=headers)
            if not response.redirected:
                return response
            location = response.header("Location")
            if not location:
                raise TransportError("redirect from %s did not include Location" % current)
            next_url = urllib.parse.urljoin(current, location)
            if validator is not None:
                validator(next_url)
            current = next_url
        raise TransportError("too many redirects while requesting %s" % url)

    def get_bytes(self, url, headers=None, timeout=None):
        response = self.request("GET", url, headers=headers, timeout=timeout)
        if response.status < 200 or response.status >= 300:
            raise TransportError("GET %s returned HTTP %d" % (url, response.status))
        return response.body

    def post_bytes(self, url, body, headers=None, timeout=None, follow_redirects=False, validator=None):
        if follow_redirects:
            response = self.request_following_redirects(
                "POST", url, body=body, headers=headers, validator=validator
            )
        else:
            response = self.request("POST", url, body=body, headers=headers, timeout=timeout)
        return response

    def open_stream(self, url, headers=None, timeout=None):
        """Open a verified HTTPS response while retaining the cookie jar."""
        request_headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if headers:
            request_headers.update({str(k): str(v) for k, v in headers.items()})
        request = urllib.request.Request(str(url), headers=request_headers, method="GET")
        try:
            return self._opener.open(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            raise TransportError("GET %s returned HTTP %d" % (url, exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError("GET %s: %s" % (url, exc)) from exc
