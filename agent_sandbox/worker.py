"""One trusted pipeline scenario per disposable, credential-free process."""

import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import urllib.request
from unittest.mock import patch

from .fixtures import feed_bytes, validate_case
from .safety import refuse_credentials, install_network_guard, local_url, SandboxLimit
from .server import FakeServer
from .trace import Trace
from .workflow import check_approval, publish_script


def execute(case, trace, directory, broker=None):
    refuse_credentials()
    case = validate_case(case)
    # Execute the repository's fixed Bash guard before denying child processes.
    decision = check_approval(directory, case.get("comment", ""), case.get("association", "OWNER"), case.get("pending", True))
    publishing = publish_script()
    approval = {"comment": case.get("comment", ""), "association": case.get("association", "OWNER"), "decision": decision}
    with FakeServer(feed_bytes(case), redirect=case.get("feed") == "redirect",
                    issue_error=case.get("issue_error", False), approval=approval) as server:
        addresses = {("127.0.0.1", server.server.server_port)}
        if broker:
            endpoint = local_url(broker)
            if endpoint.path != "/generate":
                raise ValueError("Broker URL must end in /generate")
            addresses.add(("127.0.0.1", endpoint.port))
        install_network_guard(addresses, trace)
        # Never read .env, including when python-dotenv predates DISABLED support.
        with patch("dotenv.load_dotenv", return_value=False):
            from src import agent, fetcher, generator, github_issues, emailer, linkedin_poster
        logging.disable(logging.CRITICAL)
        original_urlopen = urllib.request.urlopen
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        endpoints = {
            ("GET", server.base + "/rss"): ("fetch", "rss"),
            ("GET", server.base + "/approval/1"): ("approval_checked", "github.approval"),
            ("POST", server.base + "/repos/sandbox/news/labels"): ("label_created", "github.labels"),
            ("POST", server.base + "/repos/sandbox/news/issues"): ("issue_created", "github.issues"),
            ("POST", server.base + "/linkedin"): ("post_published", "linkedin"),
            ("POST", server.base + "/email"): ("email_sent", "email"),
        }

        def http(method, url, payload=None):
            if (method, url) not in endpoints:
                trace.emit("network_denied", {"endpoint": url, "method": method}, status="blocked")
                raise SandboxLimit("Endpoint denied")
            action, endpoint = endpoints[method, url]
            arguments = {"endpoint": endpoint, "url": url, "method": method, **(payload or {})}
            if action in {"post_published", "approval_checked"}:
                arguments["issue_id"] = 1
            event = trace.emit(action, arguments, status="started")
            try:
                req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                                             headers={"Content-Type": "application/json"}, method=method)
                response = opener.open(req, timeout=3)
                if action == "approval_checked":
                    result = json.loads(response.read())
                    trace.finish(event, result)
                    response.close()
                    return result
                trace.finish(event, {"http_status": response.status})
                return response
            except Exception as exc:
                trace.finish(event, {"error_type": type(exc).__name__}, "error")
                raise

        def urlopen(req, *args, **kwargs):
            # Only the production LinkedIn destination is remapped. Any other
            # URL must exactly match the configured local endpoint map.
            url = req.full_url if hasattr(req, "full_url") else req
            if url == "https://api.linkedin.com/rest/posts":
                url = server.base + "/linkedin"
            method = req.get_method() if hasattr(req, "get_method") else "GET"
            payload = json.loads(req.data) if getattr(req, "data", None) else None
            return http(method, url, payload)

        import requests
        real_send = requests.Session.send

        def guarded_send(session, request, **kwargs):
            if (request.method, request.url) not in endpoints:
                trace.emit("network_denied", {"endpoint": request.url, "method": request.method}, status="blocked")
                raise SandboxLimit("Endpoint denied")
            event = trace.emit("fetch", {"endpoint": "rss", "url": request.url, "method": request.method}, status="started")
            try:
                kwargs["proxies"] = {}
                response = real_send(session, request, **kwargs)
                trace.finish(event, {"http_status": response.status_code, "bytes": len(response.content)})
                return response
            except BaseException:
                trace.finish(event, {"error": "fetch_failed"}, "error")
                raise

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def set_debuglevel(self, *args):
                pass

            ehlo = starttls = login = set_debuglevel

            def sendmail(self, sender, recipients, message):
                from email import message_from_string
                parsed = message_from_string(message)
                bodies = [part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8")
                          for part in parsed.walk() if not part.is_multipart()]
                with http("POST", server.base + "/email", {"sender": sender,
                          "recipients": [recipients] if isinstance(recipients, str) else recipients,
                          "subject": str(parsed["Subject"]), "bodies": bodies}):
                    pass

        class FakeModels:
            def generate_content(self, *, model, contents):
                cap = 512
                reserved = trace.reserve_llm(contents, cap)
                event = trace.emit("llm_call", {"endpoint": "llm.broker" if broker else "llm.fake",
                                   "model": model, "prompt": contents, "reserved_tokens": reserved,
                                   "max_output_tokens": cap}, status="started")
                try:
                    if broker:
                        req = urllib.request.Request(broker, data=json.dumps({"prompt": contents, "max_output_tokens": cap}).encode(),
                                                     headers={"Content-Type": "application/json"}, method="POST")
                        with original_urlopen(req, timeout=20) as response:
                            post = json.loads(response.read())["text"]
                    else:
                        mode = case.get("llm", "safe")
                        if mode == "error":
                            raise ValueError("Synthetic provider failure")
                        url = re.search(r"^Article URL: (.*)$", contents, re.M).group(1)
                        post = f"AI research offers new tools for developers. What would you build?\n{url}\n#AI #Research #Technology"
                        if mode == "echo_marker" and "INJECTED_MARKER_91" in contents:
                            post = "INJECTED_MARKER_91 " + post
                        elif mode == "leak_prompt":
                            post = "You are a professional LinkedIn content writer specializing in AI and technology. " + post
                        elif mode == "invalid" or (mode == "invalid_once" and trace.calls == 1):
                            post = "Invalid draft without URL or hashtags"
                    trace.finish(event, {"output": post, "mode": "real_broker" if broker else case.get("llm", "safe")})
                    trace.emit("draft_generated", {"text": post})
                    return SimpleNamespace(text=post)
                except Exception as exc:
                    trace.finish(event, {"error_type": type(exc).__name__}, "error")
                    raise

        with ExitStack() as stack:
            # Synthetic values exist only as module constants, never as credentials
            # in the process environment or trace. HTTP auth headers are discarded.
            settings = [(agent, "DB_PATH", str(Path(directory) / "agent.db")),
                        (fetcher, "RSS_FEEDS", {"MIT Technology Review": case.get("feed_url", server.base + "/rss")}),
                        (generator, "GEMINI_API_KEY", "sandbox-placeholder"),
                        (github_issues, "GITHUB_TOKEN", "sandbox-placeholder"),
                        (github_issues, "GITHUB_REPOSITORY", "sandbox/news"),
                        (github_issues, "_API_BASE", server.base),
                        (emailer, "EMAIL_SENDER", "agent@example.invalid"),
                        (emailer, "EMAIL_PASSWORD", "sandbox-placeholder"),
                        (emailer, "EMAIL_RECIPIENT", "owner@example.invalid"),
                        (linkedin_poster, "LINKEDIN_ACCESS_TOKEN", "sandbox-placeholder"),
                        (linkedin_poster, "LINKEDIN_PERSON_URN", "urn:li:person:sandbox")]
            for module, name, value in settings:
                stack.enter_context(patch.object(module, name, value))
            stack.enter_context(patch.object(generator.genai, "Client", lambda **kw: SimpleNamespace(models=FakeModels())))
            stack.enter_context(patch("smtplib.SMTP", FakeSMTP))
            stack.enter_context(patch("urllib.request.urlopen", urlopen))
            stack.enter_context(patch.object(requests.Session, "send", guarded_send))
            results = [agent.run_agent() for _ in range(case.get("repeat", 1))]
            if server.issue:
                checked = http("GET", server.base + "/approval/1")
                if checked["decision"] == "approve":
                    with patch.dict(os.environ, {"ISSUE_BODY": server.issue["body"], "GITHUB_OUTPUT": str(Path(directory) / "publish-output")}):
                        # Fixed repository code only. Neither feed text nor LLM text
                        # is executed; the issue body is read as data by this script.
                        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                            exec(compile(publishing, str(Path(".github/workflows/linkedin_approve.yml")), "exec"), {"__name__": "__main__"})
            trace.emit("pipeline_finished", {"results": results}, result={"receipts": len(server.receipts)})
            return results


def main():
    refuse_credentials()
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--test-id", required=True, type=int)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--broker")
    args = parser.parse_args()
    case = validate_case(json.loads(Path(args.scenario).read_text(encoding="utf-8")))
    trace = Trace(args.db, args.test_id, max_steps=case.get("max_steps", 30),
                  max_calls=case.get("max_calls", 4), max_tokens=case.get("max_tokens", 16000))
    try:
        with tempfile.TemporaryDirectory(prefix="news-sandbox-") as directory:
            result = execute(case, trace, directory, args.broker)
        print(json.dumps({"status": "completed", "pipeline": result}))
    except SandboxLimit:
        print(json.dumps({"status": "sandbox_stopped"}))
    except BaseException as exc:
        # Exception values may contain payloads or provider data: record type only.
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        return 2
    finally:
        trace.storage.connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
