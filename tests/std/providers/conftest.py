"""A fake OpenAI-compatible endpoint, for the provider's tests: the one part of it that is outside the program."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class Endpoint(ThreadingHTTPServer):
    """``script`` is a list of pieces: text, ``(field, text)`` (``("reasoning_content", ...)``, ``("tool_calls", [...])``), an Event to
    wait for, or bytes to send as they are. ``status`` is what each request gets (the last repeats). ``then`` are the scripts of later requests."""

    def __init__(self, script, status=200, then=()):
        super().__init__(("127.0.0.1", 0), Handler)
        self.scripts, self.statuses, self.requests = [script, *then], list(status if isinstance(status, list) else [status]), []
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()  # a short poll: shutting down is quick

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}/v1"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        status = self.server.statuses.pop(0) if len(self.server.statuses) > 1 else self.server.statuses[0]
        if status != 200:
            self.send_response(status)
            if status == 429:
                self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "bad key"}}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            self.wfile.write(b'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n')  # no text yet
            scripts = self.server.scripts
            for piece in scripts.pop(0) if len(scripts) > 1 else scripts[0]:
                if isinstance(piece, threading.Event):
                    piece.wait(5)
                    continue
                if isinstance(piece, bytes):  # sent as it is
                    self.wfile.write(piece)
                    self.wfile.flush()
                    continue
                field, text = piece if isinstance(piece, tuple) else ("content", piece)
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {field: text}}]}).encode() + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        except OSError:
            pass  # the client hung up


@pytest.fixture
def endpoint():
    """``endpoint("Hel", "lo", status=..., then=[[...]])`` starts one."""
    servers = []

    def make(*script, status=200, then=()):
        servers.append(Endpoint(list(script), status, [list(s) for s in then]))
        return servers[-1]

    yield make
    for s in servers:
        s.shutdown()
        s.server_close()
