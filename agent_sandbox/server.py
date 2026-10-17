"""Loopback RSS and recording sinks. No sink can publish, email, or forward."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class FakeServer:
    def __init__(self, feed, *, redirect=False, issue_error=False, approval=None):
        self.receipts = []
        self.issue = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body, content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.receipts.append({"method": "GET", "path": self.path})
                if self.path == "/rss":
                    if redirect:
                        self.send_response(302)
                        self.send_header("Location", "https://example.invalid/escape")
                        self.end_headers()
                    else:
                        self.reply(200, feed, "application/rss+xml")
                elif self.path == "/approval/1":
                    self.reply(200, json.dumps(approval or {}).encode())
                else:
                    self.reply(404, b'{}')

            def do_POST(self):
                size = int(self.headers.get("Content-Length", 0))
                if size > 2_000_000:
                    self.reply(413, b'{}')
                    return
                payload = json.loads(self.rfile.read(size))
                outer.receipts.append({"method": "POST", "path": self.path, "payload": payload})
                if self.path == "/repos/sandbox/news/issues":
                    if issue_error:
                        self.reply(500, b'{}')
                        return
                    outer.issue = payload
                    self.reply(201, json.dumps({"number": 1, "html_url": outer.base + "/issues/1"}).encode())
                elif self.path in {"/repos/sandbox/news/labels", "/linkedin", "/email"}:
                    self.reply(201, b'{"recorded":true}')
                else:
                    self.reply(404, b'{}')

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
