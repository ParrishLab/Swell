from __future__ import annotations

import json

from swell.shared.services.instance_bridge import SingleInstanceBridge


class _FakeClientSocket:
    def __init__(self, *, should_connect: bool = True) -> None:
        self.should_connect = should_connect
        self.sent: list[bytes] = []

    def settimeout(self, _timeout: float) -> None:
        return None

    def connect(self, _address) -> None:
        if not self.should_connect:
            raise OSError("connect failed")

    def sendall(self, data: bytes) -> None:
        self.sent.append(bytes(data))

    def close(self) -> None:
        return None


class _FakeConn:
    def __init__(self, payload: str) -> None:
        self._payload = payload.encode("utf-8")
        self._reads = 0

    def settimeout(self, _timeout: float) -> None:
        return None

    def recv(self, _size: int) -> bytes:
        if self._reads > 0:
            return b""
        self._reads += 1
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        return False


class _FakeServer:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self._used = False

    def accept(self):
        if self._used:
            raise OSError("done")
        self._used = True
        return _FakeConn(self._payload), ("127.0.0.1", 9999)


class _FailingBindSocket:
    def setsockopt(self, *_args) -> None:
        return None

    def bind(self, _address) -> None:
        raise OSError("bind failed")

    def close(self) -> None:
        return None


def test_send_open_request_returns_false_when_connection_fails(monkeypatch) -> None:
    fake = _FakeClientSocket(should_connect=False)
    monkeypatch.setattr("socket.socket", lambda *_args, **_kwargs: fake)
    bridge = SingleInstanceBridge(port=55001)
    assert bridge.send_open_request("/tmp/example.sdproj", timeout=0.1) is False


def test_send_open_request_writes_json_payload(monkeypatch) -> None:
    fake = _FakeClientSocket(should_connect=True)
    monkeypatch.setattr("socket.socket", lambda *_args, **_kwargs: fake)
    bridge = SingleInstanceBridge(port=55002)
    sent = bridge.send_open_request("/tmp/example.sdproj", timeout=0.1)
    assert sent is True
    payload = json.loads(fake.sent[0].decode("utf-8").strip())
    assert payload["path"] == "/tmp/example.sdproj"


def test_primary_dispatches_received_open_request() -> None:
    received: list[str] = []
    bridge = SingleInstanceBridge(port=55003)
    bridge._server = _FakeServer('{"path": "/tmp/example.sdproj"}\n')
    bridge._serve(lambda path: received.append(path))
    assert received == ["/tmp/example.sdproj"]


def test_start_listener_returns_false_when_bind_fails(monkeypatch) -> None:
    monkeypatch.setattr("socket.socket", lambda *_args, **_kwargs: _FailingBindSocket())
    bridge = SingleInstanceBridge(port=55004)
    assert bridge.start_listener(lambda _path: None) is False
