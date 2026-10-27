"""HTTP for the online lookups: timeouts, pauses per host, one retry, stop.

Only the standard library is used: ``urllib`` honours the system proxy
(``HTTPS_PROXY`` or the Windows settings) and the system certificates, so the
portable .exe needs nothing extra. A proxy of the user's own is chosen per
request by :mod:`.proxy`.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .. import __version__

# MusicBrainz asks every client to name itself and give a contact URL.
USER_AGENT = (
    f"DiscographyAnalyzer/{__version__} "
    "( https://github.com/metalinjector/discography-analyzer )"
)
MAX_RESPONSE_BYTES = 25 * 1024 * 1024
RETRY_PAUSE = 2.0
MAX_RETRY_PAUSE = 15.0


class LookupStopped(RuntimeError):
    """The user pressed «Остановить» while a request was waiting."""


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int, reason: str) -> None:
        super().__init__(reason)
        self.url = url
        self.status = status


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[str, Mapping[str, str], float], Response]


def fetch(
    opener: urllib.request.OpenerDirector | None,
    url: str,
    headers: Mapping[str, str],
    timeout: float,
) -> Response:
    """GET ``url`` through ``opener`` (None: urllib's own, with the system proxy)."""
    request = urllib.request.Request(url, headers=dict(headers))
    open_url = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as reply:
            body = reply.read(MAX_RESPONSE_BYTES + 1)
            return Response(reply.status, body, dict(reply.headers.items()))
    except urllib.error.HTTPError as error:
        body = b""
        with contextlib.suppress(Exception):
            body = error.read(65536)
        headers = dict(error.headers.items()) if error.headers else {}
        return Response(error.code, body, headers)


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> Response:
    return fetch(None, url, headers, timeout)


def _reason(error: BaseException) -> str:
    reason = getattr(error, "reason", error)
    if isinstance(reason, TimeoutError):
        return "истекло время ожидания"
    return str(reason) or type(reason).__name__


def _retry_after(headers: Mapping[str, str]) -> float | None:
    for key, value in headers.items():
        if key.casefold() == "retry-after":
            try:
                return float(value)
            except ValueError:
                return None
    return None


class HttpClient:
    """GET requests with a minimal interval per host and one retry.

    Network errors, HTTP 429 and 5xx are retried once after a pause (the
    ``Retry-After`` header is honoured up to 15 s); other statuses fail at
    once because the same request would get the same answer.
    """

    def __init__(
        self,
        *,
        pacing: Mapping[str, float] | None = None,
        timeout: float = 20.0,
        transport: Transport | None = None,
        stop_event: threading.Event | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.pacing = dict(pacing or {})
        self.timeout = timeout
        self.transport = transport or urllib_transport
        self.stop_event = stop_event
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def get_json(self, url: str, headers: Mapping[str, str] | None = None) -> Any:
        response = self._get(url, headers)
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise HttpError(url, response.status, "ответ сервиса не в формате JSON") from exc

    def get_bytes(self, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        return self._get(url, headers).body

    def stream_bytes(
        self,
        url: str,
        progress: Callable[[int, int], None],
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        """GET ``url`` in chunks, reporting ``(done, total)`` as it goes.

        ``total`` is 0 when the server sends no ``Content-Length``. A transport
        that cannot stream (the fakes in tests, for one) falls back to one read
        and reports a single final step.
        """
        open_url = getattr(self.transport, "open", None)
        if open_url is None:
            body = self.get_bytes(url, headers)
            progress(len(body), len(body))
            return body
        host = urlsplit(url).hostname or ""
        request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
        with self._lock:
            self.check_stopped()
            self._wait_turn(host)
            try:
                with open_url(url, request_headers, self.timeout) as reply:
                    total = int(reply.headers.get("Content-Length") or 0)
                    # read1() returns what has arrived instead of waiting for
                    # the whole chunk: the percentage moves while it downloads.
                    read = getattr(reply, "read1", reply.read)
                    chunks: list[bytes] = []
                    done = 0
                    while True:
                        chunk = read(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        done += len(chunk)
                        if done > MAX_RESPONSE_BYTES:
                            raise HttpError(url, 200, "ответ сервиса слишком большой")
                        progress(done, total)
                    return b"".join(chunks)
            except (OSError, http.client.HTTPException) as exc:
                raise HttpError(url, 0, f"{host} не отвечает: {_reason(exc)}") from exc
            finally:
                self._last_request[host] = self._clock()

    def check_stopped(self) -> None:
        if self.stop_event is not None and self.stop_event.is_set():
            raise LookupStopped

    def pause(self, seconds: float) -> None:
        """Wait ``seconds``; «Остановить» interrupts the wait at once."""
        if seconds <= 0:
            return
        if self.stop_event is None:
            self._sleep(seconds)
        elif self.stop_event.wait(seconds):
            raise LookupStopped

    def _wait_turn(self, host: str) -> None:
        interval = self.pacing.get(host, 0.0)
        last = self._last_request.get(host)
        if interval and last is not None:
            self.pause(last + interval - self._clock())

    def _get(self, url: str, extra_headers: Mapping[str, str] | None) -> Response:
        host = urlsplit(url).hostname or ""
        headers = {"User-Agent": USER_AGENT, **(extra_headers or {})}
        with self._lock:
            for attempt in (1, 2):
                self.check_stopped()
                self._wait_turn(host)
                retry_after: float | None = None
                try:
                    response = self.transport(url, headers, self.timeout)
                except (OSError, http.client.HTTPException) as exc:
                    error = HttpError(url, 0, f"{host} не отвечает: {_reason(exc)}")
                else:
                    if len(response.body) > MAX_RESPONSE_BYTES:
                        raise HttpError(url, response.status, "ответ сервиса слишком большой")
                    if 200 <= response.status < 300:
                        return response
                    error = HttpError(
                        url, response.status, f"{host} ответил HTTP {response.status}"
                    )
                    if response.status != 429 and response.status < 500:
                        raise error
                    retry_after = _retry_after(response.headers)
                finally:
                    self._last_request[host] = self._clock()
                if attempt == 2:
                    raise error
                self.pause(min(max(retry_after or 0.0, RETRY_PAUSE), MAX_RETRY_PAUSE))
        raise AssertionError("unreachable")
