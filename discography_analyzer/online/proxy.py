"""Proxy for the online lookups: the system one, none, or one's own.

Deezer is closed in some countries, and a catalogue can be blocked on a
network. The user's own proxy — HTTP (``http://host:port``) or SOCKS5
(``socks5://host:port``; the proxy resolves the names) — is used only for the
services ticked in the settings, the others keep the system setting. Only the
standard library is used: urllib talks to HTTP proxies itself, and SOCKS5 is
the short handshake of RFC 1928 and RFC 1929 below.
"""

from __future__ import annotations

import functools
import http.client
import socket
import ssl
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

from .http import Response, fetch

MODES = ("system", "direct", "manual")
SOCKS_SCHEMES = {"socks5", "socks5h"}
PROXY_HINT = "Адрес прокси: http://хост:порт или socks5://хост:порт, при входе — логин:пароль@хост:порт"
SOCKS_ERRORS = {
    1: "общий сбой прокси",
    2: "соединение запрещено правилами прокси",
    3: "сеть недоступна",
    4: "узел недоступен",
    5: "в соединении отказано",
    6: "истекло время жизни",
    7: "команда не поддерживается",
    8: "тип адреса не поддерживается",
}


class ProxyError(OSError):
    """The proxy refused or broke the connection: a network error for the client."""


@dataclass(frozen=True, slots=True)
class ProxyAddress:
    scheme: str  # "http" or "socks5"
    host: str
    port: int
    username: str = ""
    password: str = ""

    @property
    def netloc(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @property
    def display(self) -> str:
        """The address without the login and the password."""
        return f"{self.scheme}://{self.netloc}"


@dataclass(frozen=True, slots=True)
class ProxySettings:
    mode: str = "system"  # "system", "direct" or "manual"
    url: str = ""
    services: frozenset[str] = frozenset({"deezer"})

    def describe(self, names: Mapping[str, str]) -> str:
        """«системный», «без прокси» or «socks5://127.0.0.1:1080 — Deezer»."""
        if self.mode == "direct":
            return "без прокси"
        if self.mode != "manual":
            return "системный"
        try:
            address = parse_proxy_url(self.url)
        except ValueError:
            return "свой прокси не задан"
        services = ", ".join(names[key] for key in names if key in self.services)
        return f"{address.display} — {services or 'ни для одного сервиса'}"


def parse_proxy_url(url: str) -> ProxyAddress:
    """The proxy address; ``ValueError`` with a message for the user otherwise."""
    text = url.strip()
    if not text:
        raise ValueError(f"Не указан адрес прокси. {PROXY_HINT}")
    if "://" not in text:
        text = f"http://{text}"  # «127.0.0.1:8080» is an HTTP proxy
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme != "http" and scheme not in SOCKS_SCHEMES:
        raise ValueError(f"Схема «{parts.scheme}» не поддерживается. {PROXY_HINT}")
    try:
        port = parts.port
    except ValueError:
        raise ValueError("Порт прокси — число от 1 до 65535") from None
    if not parts.hostname:
        raise ValueError(f"Не указан хост прокси. {PROXY_HINT}")
    if not port:
        raise ValueError(f"Не указан порт прокси. {PROXY_HINT}")
    return ProxyAddress(
        scheme="socks5" if scheme in SOCKS_SCHEMES else "http",
        host=parts.hostname,
        port=port,
        username=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
    )


def _receive(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ProxyError("прокси закрыл соединение")
        data += chunk
    return data


def _field(data: bytes, what: str) -> bytes:
    """A SOCKS string: one length byte, then the bytes."""
    if len(data) > 255:
        raise ProxyError(f"{what} длиннее 255 байт")
    return bytes([len(data)]) + data


def socks5_connect(
    proxy: ProxyAddress, host: str, port: int, timeout: float | None
) -> socket.socket:
    """A TCP connection to ``host:port`` through a SOCKS5 proxy.

    The name is sent to the proxy unresolved: the local DNS of a country that
    blocks a service may well answer with a wrong address.
    """
    sock = socket.create_connection((proxy.host, proxy.port), timeout)
    try:
        methods = b"\x00\x02" if proxy.username else b"\x00"
        sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
        version, method = _receive(sock, 2)
        if version != 5:
            raise ProxyError("это не SOCKS5-прокси")
        if method == 2 and proxy.username:
            sock.sendall(
                b"\x01"
                + _field(proxy.username.encode("utf-8"), "Логин")
                + _field(proxy.password.encode("utf-8"), "Пароль")
            )
            if _receive(sock, 2)[1] != 0:
                raise ProxyError("прокси не принял логин и пароль")
        elif method == 2:
            raise ProxyError("прокси требует логин и пароль")
        elif method != 0:
            raise ProxyError("прокси не предлагает поддерживаемый способ входа")
        try:
            name = host.encode("idna")
        except UnicodeError:
            name = host.encode("utf-8")
        # CONNECT to a domain name (address type 3).
        sock.sendall(b"\x05\x01\x00\x03" + _field(name, "Имя хоста") + port.to_bytes(2, "big"))
        _version, reply, _reserved, kind = _receive(sock, 4)
        if reply != 0:
            raise ProxyError(f"SOCKS: {SOCKS_ERRORS.get(reply, f'ошибка {reply}')}")
        # The address the proxy bound is not needed but must be read off.
        if kind == 1:
            _receive(sock, 4 + 2)
        elif kind == 3:
            _receive(sock, _receive(sock, 1)[0] + 2)
        elif kind == 4:
            _receive(sock, 16 + 2)
        else:
            raise ProxyError("непонятный ответ SOCKS-прокси")
        return sock
    except BaseException:
        sock.close()
        raise


class _SocksHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, proxy: ProxyAddress, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._proxy = proxy

    def connect(self) -> None:
        self.sock = socks5_connect(self._proxy, self.host, self.port, self.timeout)


class _SocksHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, proxy: ProxyAddress, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._proxy = proxy

    def connect(self) -> None:
        sock = socks5_connect(self._proxy, self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _SocksHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, proxy: ProxyAddress) -> None:
        super().__init__()
        self._proxy = proxy

    def http_open(self, req):
        return self.do_open(functools.partial(_SocksHTTPConnection, proxy=self._proxy), req)


class _SocksHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, proxy: ProxyAddress) -> None:
        super().__init__(context=ssl.create_default_context())
        self._proxy = proxy

    def https_open(self, req):
        return self.do_open(
            functools.partial(_SocksHTTPSConnection, proxy=self._proxy),
            req,
            context=self._context,
        )


def own_opener(proxy: ProxyAddress) -> urllib.request.OpenerDirector:
    """An opener that sends every request through ``proxy`` and nothing else."""
    if proxy.scheme == "http":
        login = ""
        if proxy.username:
            login = f"{quote(proxy.username, safe='')}:{quote(proxy.password, safe='')}@"
        url = f"http://{login}{proxy.netloc}"
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": url, "https": url}))
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),  # no system proxy under the SOCKS one
        _SocksHTTPHandler(proxy),
        _SocksHTTPSHandler(proxy),
    )


class ProxyTransport:
    """A transport that sends each request the way the settings ask for its service."""

    def __init__(
        self, settings: ProxySettings, service_hosts: Mapping[str, tuple[str, ...]]
    ) -> None:
        self.settings = settings
        self.service_hosts = service_hosts
        self._openers: dict[str, urllib.request.OpenerDirector] = {
            # build_opener() reads HTTPS_PROXY and, on Windows, the system settings.
            "system": urllib.request.build_opener(),
            "direct": urllib.request.build_opener(urllib.request.ProxyHandler({})),
        }
        if settings.mode == "manual":
            self._openers["own"] = own_opener(parse_proxy_url(settings.url))

    def service_of(self, url: str) -> str:
        host = (urlsplit(url).hostname or "").lower()
        return next(
            (
                key
                for key, suffixes in self.service_hosts.items()
                if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)
            ),
            "",
        )

    def open(self, url: str, headers: Mapping[str, str], timeout: float):
        """Open ``url`` the way the settings ask, without reading the body.

        For callers that read in chunks to show how much is left: an image
        download with a percentage under the thumbnail.
        """
        opener = self._openers[self.route(url)]
        request = urllib.request.Request(url, headers=dict(headers))
        return opener.open(request, timeout=timeout)

    def route(self, url: str) -> str:
        """«system», «direct» or «own» for this request."""
        if self.settings.mode == "direct":
            return "direct"
        if self.settings.mode == "manual" and self.service_of(url) in self.settings.services:
            return "own"
        return "system"

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> Response:
        return fetch(self._openers[self.route(url)], url, headers, timeout)
