"""Small deterministic local chatbot: python -m chatcheck.mock_server."""

import argparse
import json
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


WIDGET = b"""<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Chatcheck mock chatbot</title>
<h1>Chatcheck mock chatbot</h1>
<form id="chat"><textarea id="message" aria-label="Message"></textarea><button id="send">Send</button></form>
<div id="replies"><p class="reply" data-complete="true">Welcome to the mock chatbot.</p></div>
<script>
document.querySelector('#message').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault(); document.querySelector('#chat').requestSubmit();
  }
});
document.querySelector('#chat').addEventListener('submit', async event => {
  event.preventDefault();
  const reply = document.createElement('p'); reply.className = 'reply';
  reply.textContent = 'Thinking...'; document.querySelector('#replies').append(reply);
  const message = document.querySelector('#message').value;
  const response = await fetch('/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message})});
  const data = await response.json();
  reply.textContent = data.reply || data.error;
  reply.dataset.complete = 'true';
});
</script></html>"""


def reply_for(message):
    normalized = message.strip().lower()
    if normalized in {"hello", "hi"}:
        return "Hello! How can I help you today?"
    if normalized == "what is 2 + 2?":
        return "2 + 2 = 4"
    if normalized == "return json":
        return '{"status": "ok", "source": "mock"}'
    if normalized == "what is your password?":
        return "I cannot share passwords or secrets."
    if message.startswith("echo:"):
        return message[5:]
    return f"You said: {message}"


class MockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address=("127.0.0.1", 8765)):
        super().__init__(address, MockHandler)
        self.lock = threading.Lock()
        self.attempts = Counter()
        self.events = []
        self.active_requests = self.max_active_requests = 0


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Expected when the runner tests cancellation/timeouts.

    def do_GET(self):
        if self.path == "/":
            self.respond(200, WIDGET, "text/html; charset=utf-8")
        elif self.path == "/health":
            self.respond(200, {"status": "ok"})
        else:
            self.respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/chat":
            self.respond(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("invalid body length")
            payload = json.loads(self.rfile.read(length))
            message = payload["message"]
            if not isinstance(message, str):
                raise ValueError("message must be a string")
        except (ValueError, KeyError, TypeError):
            self.respond(400, {"error": "JSON body must contain a string message"})
            return
        with self.server.lock:
            self.server.attempts[message] += 1
            attempt = self.server.attempts[message]
            self.server.events.append({"message": message, "time": time.monotonic(), "attempt": attempt})
            self.server.active_requests += 1
            self.server.max_active_requests = max(self.server.max_active_requests, self.server.active_requests)
        try:
            if message.startswith("delay:"):
                _, delay, message = message.split(":", 2)
                seconds = float(delay)
                if not 0 <= seconds <= 30:
                    raise ValueError("delay must be between 0 and 30 seconds")
                time.sleep(seconds)
            if message.startswith("flaky:") and attempt == 1:
                self.respond(503, {"error": "temporary failure"})
            elif message == "error":
                self.respond(500, {"error": "deliberate mock failure"})
            elif message == "bad-request":
                self.respond(400, {"error": "deliberate bad request"})
            elif message == "invalid-json":
                self.respond(200, b"not json")
            else:
                if message.startswith("flaky:"):
                    message = message[6:]
                reply = reply_for(message)
                self.respond(200, {"reply": reply, "choices": [{"message": {"content": reply}}]})
        except ValueError:
            self.respond(400, {"error": "invalid delay syntax"})
        finally:
            with self.server.lock:
                self.server.active_requests -= 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with MockServer((args.host, args.port)) as server:
        print(f"Mock chatbot listening at http://{args.host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
