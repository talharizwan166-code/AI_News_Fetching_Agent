#!/usr/bin/env python3
"""Authorize LinkedIn and save token/URN locally without printing credentials."""

import argparse
from datetime import datetime, timedelta, timezone
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from dotenv import load_dotenv

from src.env_safety import check_env_not_tracked


DEFAULT_REDIRECT_URI = "https://www.linkedin.com/developers/tools/oauth/redirect"
SCOPES = "openid profile w_member_social"
TIMEOUT_SECONDS = 30


def authorization_code(callback_url: str, redirect_uri: str, state: str) -> str:
    """Validate the complete pasted callback URL, including OAuth state."""
    callback = urllib.parse.urlsplit(callback_url)
    redirect = urllib.parse.urlsplit(redirect_uri)
    if (callback.scheme, callback.netloc, callback.path) != (redirect.scheme, redirect.netloc, redirect.path):
        raise ValueError("Callback address does not match the registered redirect URI.")
    params = urllib.parse.parse_qs(callback.query)
    states = params.get("state", [])
    if len(states) != 1 or not secrets.compare_digest(states[0], state):
        raise ValueError("OAuth state mismatch. Start setup again; do not reuse this callback.")
    if "error" in params:
        raise ValueError("LinkedIn authorization was declined. Check the app products and permissions.")
    codes = params.get("code", [])
    if len(codes) != 1 or not codes[0]:
        raise ValueError("No authorization code found. Paste the complete redirect URL.")
    return codes[0]


def request_json(request: urllib.request.Request) -> dict:
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        data = json.loads(response.read())
    if not isinstance(data, dict):
        raise ValueError("LinkedIn returned an unexpected response.")
    return data


def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    payload = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code,
        "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }).encode()
    return request_json(urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken", data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    ))


def person_urn(access_token: str) -> str:
    profile = request_json(urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    ))
    subject = profile.get("sub")
    if not isinstance(subject, str) or not subject.strip() or any(c.isspace() for c in subject):
        raise ValueError("No member ID returned. Enable Sign In with LinkedIn using OpenID Connect.")
    return f"urn:li:person:{subject}"


def expiry_message(expires_in) -> str:
    try:
        seconds = int(expires_in)
        if seconds <= 0:
            raise ValueError
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    except (ValueError, TypeError, OverflowError):
        return "Expiry was not returned. LinkedIn access tokens commonly last about 60 days."
    return f"Token expires at {expires_at:%Y-%m-%d %H:%M UTC} (about {seconds / 86400:g} days)."


def ignored_output(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--", str(path)], capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redirect-uri", help="Registered callback URI, or LINKEDIN_REDIRECT_URI")
    parser.add_argument("--no-browser", action="store_true", help="Open the displayed authorization URL yourself")
    parser.add_argument("--output", type=Path, default=Path(".env.linkedin"), help="New ignored credential file (default: .env.linkedin)")
    args = parser.parse_args(argv)
    if not check_env_not_tracked():
        return 1
    load_dotenv(Path(__file__).resolve().parent / ".env")

    try:
        if args.output.exists():
            raise ValueError("Output already exists. Use --output .env.linkedin.new when renewing.")
        if not ignored_output(args.output):
            raise ValueError("Output must be Git-ignored. Use .env.linkedin or .env.linkedin.new.")
        redirect_uri = args.redirect_uri or os.getenv("LINKEDIN_REDIRECT_URI") or DEFAULT_REDIRECT_URI
        redirect = urllib.parse.urlsplit(redirect_uri)
        if redirect.scheme not in ("http", "https") or not redirect.netloc or redirect.query or redirect.fragment:
            raise ValueError("Redirect URI must be an HTTP(S) address without a query or fragment.")
        client_id = os.getenv("LINKEDIN_CLIENT_ID", "").strip() or input("LinkedIn Client ID: ").strip()
        client_secret = os.getenv("LINKEDIN_CLIENT_SECRET", "").strip() or getpass.getpass("LinkedIn Client Secret (hidden): ").strip()
        if not client_id or not client_secret:
            raise ValueError("Client ID and Client Secret are required.")

        state = secrets.token_urlsafe(32)
        auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
            "scope": SCOPES, "state": state,
        })
        print("Authorize using this URL (it contains no client secret):\n" + auth_url)
        if not args.no_browser:
            webbrowser.open(auth_url)
        print("After Allow, copy the complete address from your browser, including code and state.")
        callback = getpass.getpass("Complete redirect URL (hidden): ").strip()
        code = authorization_code(callback, redirect_uri, state)
        token_data = exchange_code(code, client_id, client_secret, redirect_uri)
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip() or any(c.isspace() for c in access_token):
            raise ValueError("LinkedIn did not return a usable access token.")
        urn = person_urn(access_token)
        # Exclusive creation prevents accidentally overwriting existing credentials.
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("LINKEDIN_ACCESS_TOKEN=" + json.dumps(access_token) + "\n")
            output.write("LINKEDIN_PERSON_URN=" + json.dumps(urn) + "\n")
        print(f"Credentials saved to {args.output}; token and member ID were not printed.")
        print(expiry_message(token_data.get("expires_in")))
        print("Before expiry, rerun with --output .env.linkedin.new and replace the GitHub Secrets.")
        print("On HTTP 401, renew authorization; tokens can also be revoked before their expiry date.")
        print("Open the credential file privately and copy values to .env and/or GitHub Actions Secrets.")
        print("Do not paste credentials into chat, issues, screenshots, or workflow logs.")
        return 0
    except urllib.error.HTTPError as error:
        if error.code == 401:
            print("ERROR: LinkedIn HTTP 401. Token invalid/expired; rerun authorization.")
        elif error.code == 403:
            print("ERROR: LinkedIn HTTP 403. Check OpenID Connect and Share on LinkedIn product access.")
        else:
            print(f"ERROR: LinkedIn HTTP {error.code}. Check redirect URI, scopes, or request a fresh code.")
        return 1
    except urllib.error.URLError:
        print("ERROR: Cannot reach LinkedIn. Check your connection and retry setup.")
        return 1
    except ValueError as error:
        print(f"ERROR: {error}")
        return 1
    except OSError:
        print("ERROR: Check network connectivity, Git access, and output-file permissions.")
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        print("Setup cancelled.")
        raise SystemExit(1)
