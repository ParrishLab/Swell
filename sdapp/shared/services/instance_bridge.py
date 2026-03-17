from __future__ import annotations

import getpass
import hashlib
import json
import os
import socket
import threading
from typing import Callable


def _default_port() -> int:
    override = str(os.environ.get("SDAPP_INSTANCE_BRIDGE_PORT", "")).strip()
    if override:
        try:
            value = int(override)
        except ValueError:
            value = 0
        if 1 <= value <= 65535:
            return value
    user = str(getpass.getuser() or "unknown")
    digest = hashlib.sha256(f"sdapp.instance_bridge:{user}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:2], byteorder="big", signed=False)
    return 49152 + (value % 10000)


class SingleInstanceBridge:
    """Lightweight localhost IPC bridge used to forward open-project requests."""

    def __init__(self, host: str = "127.0.0.1", port: int | None = None) -> None:
        self.host = str(host)
        self.port = int(port if port is not None else _default_port())
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def send_open_request(self, path: str, timeout: float = 0.6) -> bool:
        payload = {"path": str(path)}
        data = (json.dumps(payload) + "\n").encode("utf-8")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(float(timeout))
            sock.connect((self.host, self.port))
            sock.sendall(data)
            return True
        except OSError:
            return False
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def start_listener(self, on_open_path: Callable[[str], None]) -> bool:
        with self._lock:
            if self._server is not None:
                return True
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((self.host, self.port))
                server.listen(8)
                server.settimeout(0.5)
            except OSError:
                try:
                    server.close()
                except OSError:
                    pass
                return False
            self._stop.clear()
            self._server = server
            self._thread = threading.Thread(target=self._serve, args=(on_open_path,), daemon=True)
            self._thread.start()
            return True

    def _serve(self, on_open_path: Callable[[str], None]) -> None:
        while not self._stop.is_set():
            server = self._server
            if server is None:
                return
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(0.5)
                    chunks: list[bytes] = []
                    while True:
                        part = conn.recv(4096)
                        if not part:
                            break
                        chunks.append(part)
                        if b"\n" in part:
                            break
                    raw = b"".join(chunks).decode("utf-8", errors="replace")
                    data = json.loads(raw.strip() or "{}")
                    path = data.get("path")
                    if isinstance(path, str) and path.strip():
                        on_open_path(path)
                except Exception:
                    continue

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            server = self._server
            self._server = None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=1.0)
