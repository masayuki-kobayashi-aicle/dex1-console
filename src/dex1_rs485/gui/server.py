"""HTTP front end: the page, a server-sent-events stream for the log view, and POST /api/<action>.

Safe by construction for a machine that moves a robot hand:
- binds to 127.0.0.1 only (there is deliberately no option to listen on other addresses);
- rejects any request whose Host is not this server (blocks DNS rebinding);
- POSTs need the per-run token, JSON content type and, when sent, a same-origin Origin (blocks other web pages).
"""
from __future__ import annotations

import hmac
import json
import queue
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from ..config import Config
from ..i18n import language, t
from .events import EventBus
from .session import HandSession

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY = 4096
HEARTBEAT_S = 15.0
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:"


class GuiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, session: HandSession, bus: EventBus) -> None:
        super().__init__((HOST, port), Handler)
        self.session, self.bus, self.token = session, bus, secrets.token_urlsafe(16)
        self.hosts = {f"{HOST}:{self.server_port}", f"localhost:{self.server_port}"}
        self.closing = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.server_port}/"


def _page(token: str) -> bytes:
    html = resources.files("dex1_rs485.gui").joinpath("static/index.html").read_text(encoding="utf-8")
    return html.replace("__TOKEN__", token).replace("__LANG__", language()).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server: GuiServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - quiet; the log view is the record
        pass

    # --- helpers -----------------------------------------------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.server.hosts

    def _token_ok(self, token: str) -> bool:
        return hmac.compare_digest(token.encode(), self.server.token.encode())

    # --- GET ---------------------------------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._json(403, {"error": "bad host"})
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(200, _page(self.server.token), "text/html; charset=utf-8")
        if url.path == "/events":
            token = parse_qs(url.query).get("token", [""])[0]
            return self._events() if self._token_ok(token) else self._json(403, {"error": "bad token"})
        self._json(404, {"error": "not found"})

    def _events(self) -> None:
        past, q = self.server.bus.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            for event in past:
                self._write_event(event)
            self._write_event({"type": "state", **self.server.session.state()})
            while not self.server.closing.is_set():
                try:
                    self._write_event(q.get(timeout=HEARTBEAT_S))
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.bus.unsubscribe(q)
            self.close_connection = True

    def _write_event(self, event: dict) -> None:
        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
        self.wfile.flush()

    # --- POST --------------------------------------------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._json(403, {"error": "bad host"})
        origin = self.headers.get("Origin")
        if origin is not None and origin.removeprefix("http://") not in self.server.hosts:
            return self._json(403, {"error": "bad origin"})
        if not self._token_ok(self.headers.get("X-Dex1-Token", "")):
            return self._json(403, {"error": "bad token"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json(415, {"error": "JSON only"})
        params = self._read_params()
        if params is None:
            return self._json(400, {"error": "bad request body"})
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        self._json(*self._dispatch(path.removeprefix("/api/"), params))

    def _read_params(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_BODY:
                return None
            params = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return None
        return params if isinstance(params, dict) else None

    def _dispatch(self, action: str, params: dict) -> tuple[int, dict]:
        session = self.server.session
        if action == "answer":
            qid, value = params.get("qid"), params.get("value")
            ok = isinstance(qid, int) and value in ("ok", "yes", "no") and session.prompter.answer(qid, value)
            return (200, {"ok": True}) if ok else (409, {"error": "no such question"})
        return session.do(action, params)


def serve(cfg: Config, port: int = DEFAULT_PORT, open_browser: bool = True, skip_preflight: bool = False,
          write_log: bool = True) -> int:
    bus = EventBus()
    session = HandSession(cfg, bus, skip_preflight, write_log=write_log)
    server = GuiServer(port, session, bus)
    print(t("gui_url", url=server.url), flush=True)
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.closing.set()
        session.close()
        server.server_close()
    return 0
