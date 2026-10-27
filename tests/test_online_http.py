from __future__ import annotations

import threading
import unittest

from discography_analyzer.online.http import (
    USER_AGENT,
    HttpClient,
    HttpError,
    LookupStopped,
    Response,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def client_with(responses, *, pacing=None, stop_event=None):
    """A client whose transport answers from ``responses`` in order."""
    clock = FakeClock()
    calls: list[tuple[str, dict]] = []
    answers = list(responses)

    def transport(url, headers, timeout):
        calls.append((url, dict(headers)))
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    client = HttpClient(
        pacing=pacing,
        transport=transport,
        stop_event=stop_event,
        clock=clock.time,
        sleep=clock.sleep,
    )
    return client, calls, clock


class HttpClientTests(unittest.TestCase):
    def test_json_is_decoded_and_the_client_names_itself(self) -> None:
        client, calls, _clock = client_with([Response(200, '{"ok": "да"}'.encode())])

        data = client.get_json("https://itunes.apple.com/search?term=x")

        self.assertEqual(data, {"ok": "да"})
        self.assertEqual(calls[0][1]["User-Agent"], USER_AGENT)
        self.assertIn("github.com/metalinjector/discography-analyzer", USER_AGENT)

    def test_requests_to_one_host_keep_the_pause(self) -> None:
        client, calls, clock = client_with(
            [Response(200, b"{}")] * 3, pacing={"itunes.apple.com": 3.0}
        )

        client.get_json("https://itunes.apple.com/search?term=a")
        client.get_json("https://itunes.apple.com/lookup?id=1")
        # Another host has its own clock: no wait for the artwork server.
        client.get_bytes("https://is1-ssl.mzstatic.com/image.jpg")

        self.assertEqual(clock.sleeps, [3.0])
        self.assertEqual(len(calls), 3)

    def test_server_errors_are_retried_once_after_retry_after(self) -> None:
        client, calls, clock = client_with(
            [Response(503, b"", {"Retry-After": "7"}), Response(200, b"[1]")]
        )

        self.assertEqual(client.get_json("https://api.deezer.com/album/1"), [1])
        self.assertEqual(len(calls), 2)
        self.assertEqual(clock.sleeps, [7.0])

    def test_a_long_retry_after_is_capped(self) -> None:
        client, _calls, clock = client_with(
            [Response(429, b"", {"retry-after": "3600"}), Response(200, b"{}")]
        )

        client.get_json("https://musicbrainz.org/ws/2/release")

        self.assertEqual(clock.sleeps, [15.0])

    def test_client_errors_are_not_retried(self) -> None:
        client, calls, _clock = client_with([Response(404, b"")])

        with self.assertRaises(HttpError) as raised:
            client.get_json("https://api.discogs.com/releases/1")

        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(len(calls), 1)

    def test_a_network_failure_twice_is_an_error_with_the_host(self) -> None:
        client, calls, _clock = client_with([OSError("reset"), TimeoutError()])

        with self.assertRaises(HttpError) as raised:
            client.get_json("https://itunes.apple.com/search")

        self.assertEqual(len(calls), 2)
        self.assertIn("itunes.apple.com", str(raised.exception))
        self.assertIn("истекло время ожидания", str(raised.exception))

    def test_a_page_instead_of_json_is_reported(self) -> None:
        client, _calls, _clock = client_with([Response(200, b"<html>captcha</html>")])

        with self.assertRaisesRegex(HttpError, "не в формате JSON"):
            client.get_json("https://api.deezer.com/search/album")

    def test_stop_interrupts_before_the_request_and_during_a_pause(self) -> None:
        stop = threading.Event()
        stop.set()
        client, calls, _clock = client_with([Response(200, b"{}")], stop_event=stop)

        with self.assertRaises(LookupStopped):
            client.get_json("https://itunes.apple.com/search")
        with self.assertRaises(LookupStopped):
            client.pause(30)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()


class StreamingTests(unittest.TestCase):
    """The cover download reports how much is left, so the panel shows a percent."""

    def test_bytes_arrive_in_chunks_and_every_step_is_reported(self) -> None:
        class Reply:
            headers = {"Content-Length": "10"}

            def __init__(self) -> None:
                self.parts = [b"aaaa", b"bbb", b"ccc"]

            def read(self, size: int) -> bytes:
                return self.parts.pop(0) if self.parts else b""

            def __enter__(self):
                return self

            def __exit__(self, *args) -> None:
                return None

        class Transport:
            def open(self, url, headers, timeout):
                return Reply()

        client = HttpClient(transport=Transport())
        steps: list[tuple[int, int]] = []
        body = client.stream_bytes("https://is1-ssl.mzstatic.com/x.jpg", lambda done, total: steps.append((done, total)))
        self.assertEqual(body, b"aaaabbbccc")
        self.assertEqual(steps, [(4, 10), (7, 10), (10, 10)])

    def test_a_transport_without_streaming_is_read_at_once(self) -> None:
        client, _calls, _clock = client_with([Response(200, b"12345", {})])
        steps: list[tuple[int, int]] = []
        body = client.stream_bytes("https://example.org/x.jpg", lambda done, total: steps.append((done, total)))
        self.assertEqual(body, b"12345")
        self.assertEqual(steps, [(5, 5)])

    def test_the_client_names_itself_when_streaming(self) -> None:
        seen: dict = {}

        class Reply:
            headers = {"Content-Length": "0"}

            def read(self, size: int) -> bytes:
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *args) -> None:
                return None

        class Transport:
            def open(self, url, headers, timeout):
                seen.update(headers)
                return Reply()

        HttpClient(transport=Transport()).stream_bytes(
            "https://example.org/x.jpg", lambda done, total: None
        )
        self.assertEqual(seen["User-Agent"], USER_AGENT)
