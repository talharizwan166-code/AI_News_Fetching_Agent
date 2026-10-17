"""Fail closed before importing the agent, loading dotenv, or opening a socket."""

import os
import re
import sys
from urllib.parse import urlsplit


class SandboxRefusal(ValueError):
    pass


class SandboxLimit(BaseException):
    """Not swallowed by the production pipeline's retry/error handlers."""


def refuse_credentials(environment=None):
    environment = os.environ if environment is None else environment
    sensitive = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|DSN|CONNECTION_STRING)", re.I)
    accounts = {"EMAIL_SENDER", "EMAIL_RECIPIENT", "SENDER_EMAIL", "RECEIVER_EMAIL",
                "LINKEDIN_PERSON_URN", "GITHUB_REPOSITORY", "GOOGLE_APPLICATION_CREDENTIALS"}
    # Values and even environment variable names are deliberately never echoed.
    if any(value and (sensitive.search(name) or name.upper() in accounts) for name, value in environment.items()):
        raise SandboxRefusal("Sandbox refused: credential or account configuration is present in the environment. Use a clean shell.")


def clean_environment():
    refuse_credentials()
    # Do not inherit proxy, dotenv, provider config, PYTHONPATH, startup hooks,
    # or arbitrary agent configuration. Windows needs SystemRoot for subprocesses.
    names = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LC_ALL"}
    env = {k: v for k, v in os.environ.items() if k.upper() in names}
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1")
    return env


def local_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise SandboxRefusal("Only explicit http://127.0.0.1:port endpoints are allowed")
    return parsed


def install_network_guard(addresses, trace):
    """Defense in depth for this trusted Python target, not an OS security boundary.

    Audit hooks cover requests, urllib, SMTP and raw Python sockets. Native code
    capable of bypassing Python is out of scope; untrusted executable code is not run.
    """
    def audit(event, args):
        denied = False
        if event in {"socket.connect", "socket.sendto"}:
            address = args[1] if event == "socket.connect" else args[-1]
            denied = not isinstance(address, tuple) or tuple(address[:2]) not in addresses
        elif event == "socket.getaddrinfo":
            denied = args[0] != "127.0.0.1" or args[1] not in {port for _, port in addresses}
        elif event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            denied = True
        if denied:
            trace.emit("network_denied", {"operation": event}, status="blocked")
            raise SandboxLimit("Sandbox blocked an unapproved external operation")
    sys.addaudithook(audit)
