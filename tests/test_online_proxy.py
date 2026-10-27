"""Proxy routing with real local servers: an HTTP proxy, a SOCKS5 one, a site."""

from __future__ import annotations

import http.server
import json
import os
import socket
import socketserver
import threading
import unittest
from unittest.mock import patch

from discography_analyzer.online.deezer import DeezerProvider
from discography_analyzer.online.discogs import DiscogsProvider
from discography_analyzer.online.http import HttpClient, HttpError, Response
from discography_analyzer.online.lookup import SERVICE_HOSTS, SERVICE_NAMES, make_client
from discography_analyzer.online.preferences import OnlinePreferences
from discography_analyzer.online.proxy import (
    ProxyError,
    ProxySettings,
    ProxyTransport,
    parse_proxy_url,
    socks5_connect,
)
from discography_analyzer.online.release import LookupOptions

ANSWER = {"open": True, "country": "Germany"}


class Recorder(http.server.BaseHTTPRequestHandler):
    """Answers every GET with ANSWER and records what it was asked."""

    def do_GET(self) -> None:
        self.server.seen.append((self.path, self.headers.get("Proxy-Authorization")))
        body = json.dumps(ANSWER).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        pass


def receive(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


class Socks5(socketserver.BaseRequestHandler):
    """A tiny SOCKS5 server: every CONNECT goes to 127.0.0.1 on the asked port."""

    def handle(self) -> None:
        server, sock = self.server, self.request
        _version, count = receive(sock, 2)
        receive(sock, count)
        if server.credentials:
            sock.sendall(b"\x05\x02")
            _version, length = receive(sock, 2)
            user = receive(sock, length).decode()
            password = receive(sock, receive(sock, 1)[0]).decode()
            accepted = (user, password) == server.credentials
            sock.sendall(b"\x01\x00" if accepted else b"\x01\x01")
            if not accepted:
                return
        else:
            sock.sendall(b"\x05\x00")
        _version, _command, _reserved, kind = receive(sock, 4)
        name = receive(sock, receive(sock, 1)[0]).decode() if kind == 3 else "?"
        port = int.from_bytes(receive(sock, 2), "big")
        server.connects.append((name, port))
        if server.reply:
            sock.sendall(bytes([5, server.reply, 0, 1]) + bytes(6))
            return
        sock.sendall(b"\x05\x00\x00\x01" + bytes(6))
        with socket.create_connection(("127.0.0.1", port)) as backend:
            request = b""
            while b"\r\n\r\n" not in request:
                request += sock.recv(4096)
            backend.sendall(request)
            while chunk := backend.recv(4096):
                sock.sendall(chunk)


class LocalServers(unittest.TestCase):
    def start(self, server: socketserver.BaseServer) -> int:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def site(self) -> tuple[int, list]:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        server.seen = []
        return self.start(server), server.seen

    def socks(self, *, credentials=None, reply: int = 0) -> tuple[int, list]:
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Socks5)
        server.daemon_threads = True
        server.credentials, server.reply, server.connects = credentials, reply, []
        return self.start(server), server.connects


class ProxyAddressTests(unittest.TestCase):
    def test_addresses_people_type(self) -> None:
        self.assertEqual(parse_proxy_url("127.0.0.1:8080").display, "http://127.0.0.1:8080")
        socks = parse_proxy_url("socks5h://user:p%40ss@proxy.example:1080")
        self.assertEqual((socks.scheme, socks.username, socks.password), ("socks5", "user", "p@ss"))
        self.assertEqual(socks.display, "socks5://proxy.example:1080")
        self.assertEqual(parse_proxy_url("http://[::1]:3128").netloc, "[::1]:3128")

    def test_unusable_addresses_explain_themselves(self) -> None:
        for text, message in (
            ("", "Не указан адрес"),
            ("socks4://127.0.0.1:1080", "не поддерживается"),
            ("http://127.0.0.1", "Не указан порт"),
            ("http://127.0.0.1:99999", "Порт прокси"),
            ("http://:8080", "Не указан хост"),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                parse_proxy_url(text)

    def test_the_description_hides_the_login(self) -> None:
        own = ProxySettings("manual", "socks5://me:secret@10.0.0.1:1080", frozenset({"deezer", "apple"}))

        self.assertEqual(own.describe(SERVICE_NAMES), "socks5://10.0.0.1:1080 — Apple Music, Deezer")
        self.assertEqual(ProxySettings().describe(SERVICE_NAMES), "системный")
        self.assertEqual(ProxySettings("direct").describe(SERVICE_NAMES), "без прокси")
        self.assertEqual(ProxySettings("manual", "").describe(SERVICE_NAMES), "свой прокси не задан")


class RoutingTests(unittest.TestCase):
    def test_only_the_chosen_services_use_the_own_proxy(self) -> None:
        transport = ProxyTransport(
            ProxySettings("manual", "socks5://127.0.0.1:1080", frozenset({"deezer"})), SERVICE_HOSTS
        )

        self.assertEqual(transport.route("https://api.deezer.com/search/album?q=x"), "own")
        self.assertEqual(transport.route("https://e-cdns-images.dzcdn.net/images/cover/x.jpg"), "own")
        self.assertEqual(transport.route("https://itunes.apple.com/search?term=x"), "system")
        # A look-alike domain is not Deezer.
        self.assertEqual(transport.route("https://notdeezer.com/"), "system")
        self.assertEqual(transport.service_of("https://ia800.us.archive.org/x.jpg"), "musicbrainz")

    def test_without_proxy_every_service_goes_direct(self) -> None:
        transport = ProxyTransport(ProxySettings("direct"), SERVICE_HOSTS)

        self.assertEqual(transport.route("https://api.deezer.com/infos"), "direct")
        self.assertEqual(transport.route("https://musicbrainz.org/ws/2/release"), "direct")

    def test_an_unusable_own_proxy_is_an_error_before_any_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "Не указан порт"):
            make_client(proxy=ProxySettings("manual", "http://127.0.0.1"))

    def test_preferences_keep_the_proxy(self) -> None:
        stored = OnlinePreferences(
            proxy_mode="manual", proxy_url="http://127.0.0.1:3128", proxy_services=["deezer"]
        )

        self.assertEqual(stored.proxy, ProxySettings("manual", "http://127.0.0.1:3128", frozenset({"deezer"})))
        self.assertEqual(OnlinePreferences(proxy_mode="vpn").proxy.mode, "system")


class HttpProxyTests(LocalServers):
    def test_an_http_proxy_gets_the_request_with_the_login(self) -> None:
        port, seen = self.site()
        settings = ProxySettings("manual", f"http://me:p%40ss@127.0.0.1:{port}", frozenset({"deezer"}))

        response = ProxyTransport(settings, SERVICE_HOSTS)("http://api.deezer.com/infos", {}, 5)

        self.assertEqual(json.loads(response.body), ANSWER)
        path, authorization = seen[0]
        # A proxy sees the full address, a site only the path.
        self.assertEqual(path, "http://api.deezer.com/infos")
        self.assertEqual(authorization, "Basic bWU6cEBzcw==")  # me:p@ss

    def test_direct_ignores_the_proxy_of_the_environment(self) -> None:
        port, seen = self.site()
        url = f"http://127.0.0.1:{port}/infos"
        dead_proxy = {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
        with patch.dict(os.environ, {**dead_proxy, "no_proxy": "", "NO_PROXY": ""}):
            response = ProxyTransport(ProxySettings("direct"), SERVICE_HOSTS)(url, {}, 5)
            with self.assertRaises(OSError):
                ProxyTransport(ProxySettings("system"), SERVICE_HOSTS)(url, {}, 5)

        self.assertEqual(response.status, 200)
        self.assertEqual(seen, [("/infos", None)])


class Socks5Tests(LocalServers):
    def test_a_socks5_proxy_resolves_the_name_and_relays(self) -> None:
        site_port, seen = self.site()
        socks_port, connects = self.socks(credentials=("me", "secret"))
        settings = ProxySettings(
            "manual", f"socks5://me:secret@127.0.0.1:{socks_port}", frozenset({"deezer"})
        )

        response = ProxyTransport(settings, SERVICE_HOSTS)(
            f"http://api.deezer.com:{site_port}/infos", {"User-Agent": "test"}, 5
        )

        self.assertEqual(json.loads(response.body), ANSWER)
        # The name reached the proxy unresolved.
        self.assertEqual(connects, [("api.deezer.com", site_port)])
        self.assertEqual(seen[0][0], "/infos")

    def client(self, settings: ProxySettings) -> HttpClient:
        return HttpClient(
            transport=ProxyTransport(settings, SERVICE_HOSTS), sleep=lambda _seconds: None
        )

    def test_a_refused_login_and_a_refused_connection_are_network_errors(self) -> None:
        socks_port, _connects = self.socks(credentials=("me", "secret"))
        wrong = ProxySettings("manual", f"socks5://me:wrong@127.0.0.1:{socks_port}", frozenset({"deezer"}))
        with self.assertRaisesRegex(HttpError, "api.deezer.com не отвечает: прокси не принял логин и пароль"):
            self.client(wrong).get_json("http://api.deezer.com:80/")

        refusing_port, _ = self.socks(reply=5)
        settings = ProxySettings("manual", f"socks5://127.0.0.1:{refusing_port}", frozenset({"deezer"}))
        with self.assertRaisesRegex(HttpError, "api.deezer.com не отвечает: SOCKS: в соединении отказано"):
            self.client(settings).get_json("http://api.deezer.com:80/infos")

    def test_an_http_proxy_given_as_socks5_is_named(self) -> None:
        class HttpOnly(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                self.request.recv(16)
                self.request.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), HttpOnly)
        server.daemon_threads = True
        port = self.start(server)

        with self.assertRaisesRegex(ProxyError, "это не SOCKS5-прокси"):
            socks5_connect(parse_proxy_url(f"socks5://127.0.0.1:{port}"), "api.deezer.com", 443, 5)


class ServiceCheckTests(unittest.TestCase):
    def client(self, answers: dict[str, object]) -> HttpClient:
        def transport(url, headers, timeout):
            for prefix, answer in answers.items():
                if url.startswith(prefix):
                    if isinstance(answer, int):
                        return Response(answer, b"{}")
                    return Response(200, json.dumps(answer).encode())
            return Response(404, b"")

        return HttpClient(transport=transport, sleep=lambda _seconds: None)

    def test_deezer_says_where_it_is_closed(self) -> None:
        closed = DeezerProvider(
            self.client({"https://api.deezer.com/infos": {"country": "Russia", "open": False}}),
            LookupOptions(),
        )
        opened = DeezerProvider(
            self.client({"https://api.deezer.com/infos": {"country": "Germany", "open": True}}),
            LookupOptions(),
        )

        status = closed.check()
        self.assertFalse(status.available)
        self.assertIn("Russia", status.text)
        # The live API still answers searches from a closed country.
        self.assertIn("поиск и теги работают", status.text)
        self.assertEqual(opened.check().text, "доступен, страна запроса — Germany")

    def test_discogs_checks_the_token_when_there_is_one(self) -> None:
        with_token = DiscogsProvider(
            self.client({"https://api.discogs.com/oauth/identity": {"username": "collector"}}),
            LookupOptions(discogs_token="test-token"),
        )
        bad_token = DiscogsProvider(
            self.client({"https://api.discogs.com/oauth/identity": 401}),
            LookupOptions(discogs_token="wrong"),
        )
        without = DiscogsProvider(
            self.client({"https://api.discogs.com/": {"hello": "Welcome"}}), LookupOptions()
        )

        self.assertIn("collector", with_token.check().text)
        with self.assertRaisesRegex(HttpError, "не принял токен"):
            bad_token.check()
        self.assertEqual(without.check().text, "отвечает; для поиска нужен токен")


if __name__ == "__main__":
    unittest.main()
