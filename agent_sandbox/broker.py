"""Optional credential holder OUTSIDE the sandbox. Disabled unless explicitly started.

The sandbox itself never receives the API key. This broker can only call Gemini;
it cannot access GitHub, LinkedIn or email. No provider errors or headers are logged.
"""

import argparse
from getpass import getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from .safety import refuse_credentials


class Budget:
    def __init__(self, calls=5, tokens=20000):
        if type(calls) is not int or not 1 <= calls <= 30 or type(tokens) is not int or not 1 <= tokens <= 100000:
            raise ValueError("Broker caps must be 1..30 calls and 1..100000 reserved tokens")
        self.max_calls, self.max_tokens = calls, tokens
        self.calls = self.tokens = 0

    def reserve(self, prompt, output):
        amount = len(prompt.encode("utf-8")) + output
        if self.calls >= self.max_calls or self.tokens + amount > self.max_tokens:
            return False
        self.calls += 1
        self.tokens += amount
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-real-llm", action="store_true", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--max-calls", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=20000)
    args = parser.parse_args()
    refuse_credentials()
    budget = Budget(args.max_calls, args.max_tokens)
    # No command line key, environment key, dotenv, file, or saved SDK request.
    key = getpass("Gemini API key (hidden, broker memory only): ")
    if not key:
        raise ValueError("A key is required")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key, http_options=types.HttpOptions(
        timeout=15000, retry_options=types.HttpRetryOptions(attempts=1)))
    del key

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, value):
            data = json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/generate" or self.headers.get("Origin"):
                self.reply(403, {"error": "denied"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 1 <= length <= 20000:
                    raise ValueError()
                payload = json.loads(self.rfile.read(length))
                prompt, output = payload["prompt"], payload["max_output_tokens"]
                if not isinstance(prompt, str) or type(output) is not int or not 1 <= output <= 512:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                self.reply(400, {"error": "invalid_request"})
                return
            if not budget.reserve(prompt, output):
                self.reply(429, {"error": "budget_exhausted"})
                return
            try:
                response = client.models.generate_content(model=args.model, contents=prompt,
                                                          config=types.GenerateContentConfig(max_output_tokens=output))
                self.reply(200, {"text": response.text or ""})
            except Exception:
                self.reply(502, {"error": "provider_failed"})

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Real Gemini broker listening on http://127.0.0.1:{args.port}/generate; caps: {args.max_calls} calls, {args.max_tokens} reserved tokens")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        client.close()


if __name__ == "__main__":
    main()
