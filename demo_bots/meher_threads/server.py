"""Loopback HTTP server shared by the three demo modes."""

import argparse
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .bot import StoreBot
from .knowledge import DEFAULT_FAQ, DEFAULT_PRIVATE


PORTS = {"weak": 8766, "hardened": 8767, "llm": 8768, "mutant": 8769}


class StoreServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, bot, port=0):
        self.bot = bot
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def respond(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, {"status": "ok", "mode": self.server.bot.mode})
        else:
            self.respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/chat":
            self.respond(404, {"error": "not found"})
            return
        if self.headers.get_content_type() != "application/json":
            self.respond(415, {"error": "Content-Type must be application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32_768 or self.headers.get("Transfer-Encoding"):
                self.respond(413, {"error": "Provide a JSON body of at most 32768 bytes"})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"message"}:
                raise ValueError("message only")
            message = payload["message"]
            if not isinstance(message, str) or not message.strip():
                raise ValueError("nonempty message required")
        except (ValueError, UnicodeError, TimeoutError):
            self.respond(400, {"error": "JSON body must contain only a nonempty string 'message'"})
            return
        try:
            reply = self.server.bot.reply(message)
            self.respond(200, {"reply": reply, "choices": [{"message": {"content": reply}}]})
        except Exception:
            # No raw exceptions, model diagnostics, prompts or keys in responses/logs.
            self.respond(502, {"error": "Chatbot response unavailable; check the target configuration"})


@contextmanager
def background_server(bot, port=0):
    with StoreServer(bot, port) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a local Meher Threads demo chatbot (hardened by default).")
    parser.add_argument("--mode", choices=list(PORTS), default="hardened")
    parser.add_argument("--mutant", help="Mutant ID from demo_bots/meher_threads/mutants.json; requires --mode mutant")
    parser.add_argument("--port", type=int, help="Override the mode's default loopback port")
    parser.add_argument("--faq", default=str(DEFAULT_FAQ))
    parser.add_argument("--private-fixture", default=str(DEFAULT_PRIVATE))
    args = parser.parse_args(argv)
    if (args.mode == "mutant") != bool(args.mutant):
        parser.error("Use --mode mutant together with --mutant <id>")
    bot = None
    try:
        kwargs = {"faq_path": args.faq, "private_path": args.private_fixture}
        if args.mode == "llm":
            from .llm import LLMBot
            bot = LLMBot(**kwargs)
        elif args.mode == "mutant":
            from .mutants import MutantBot
            bot = MutantBot(args.mutant, **kwargs)
        else:
            bot = StoreBot(args.mode, **kwargs)
        with StoreServer(bot, PORTS[args.mode] if args.port is None else args.port) as server:
            print(f"Meher Threads {args.mode}: {server.url} (POST /chat)", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    finally:
        if bot is not None and hasattr(bot, "close"):
            bot.close()
    return 0
