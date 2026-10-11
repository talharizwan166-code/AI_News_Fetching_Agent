#!/usr/bin/env python3
"""
LinkedIn OAuth Setup - Get your access token and person URN.

Usage:
    python setup_linkedin.py --client-id YOUR_ID --client-secret YOUR_SECRET

Or set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET env vars.
"""

import json
import os
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
import argparse


DEFAULT_REDIRECT_URI = "https://www.linkedin.com/developers/tools/oauth/redirect"
DEFAULT_SCOPES = "openid profile w_member_social"


def main():
    parser = argparse.ArgumentParser(description="LinkedIn OAuth setup for AI News Agent")
    parser.add_argument("--client-id", help="LinkedIn App Client ID (or set LINKEDIN_CLIENT_ID env)")
    parser.add_argument("--client-secret", help="LinkedIn App Client Secret (or set LINKEDIN_CLIENT_SECRET env)")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI, help="OAuth redirect URI")
    parser.add_argument("--scopes", default=DEFAULT_SCOPES, help="OAuth scopes")
    args = parser.parse_args()

    client_id = args.client_id or os.getenv("LINKEDIN_CLIENT_ID")
    client_secret = args.client_secret or os.getenv("LINKEDIN_CLIENT_SECRET")

    if not client_id:
        client_id = input("Enter your LinkedIn App Client ID: ").strip()
    if not client_secret:
        client_secret = input("Enter your LinkedIn App Client Secret: ").strip()

    if not client_id or not client_secret:
        print("ERROR: Client ID and Client Secret are required.")
        print("Get them from: https://www.linkedin.com/developers/")
        return 1

    print("=" * 60)
    print("LinkedIn OAuth Setup for AI News Agent")
    print("=" * 60)
    print(f"Client ID: {client_id}")
    print(f"Redirect URI: {args.redirect_uri}")
    print(f"Scopes: {args.scopes}")
    print()

    # Step 1: Authorization URL
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": args.redirect_uri,
        "scope": args.scopes,
        "state": "setup_linkedin",
    }
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(auth_params)

    print("Opening browser for authorization...")
    print(f"If the browser doesn't open, copy this URL manually:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("After clicking 'Allow', LinkedIn will show you an authorization code.")
    print("Copy that code and paste it below.\n")
    code = input("Paste the authorization code here: ").strip()

    if not code:
        print("ERROR: No authorization code entered.")
        return 1

    print("\nExchanging code for access token...")

    # Step 2: Exchange code for access token
    token_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": args.redirect_uri,
    }).encode()

    req = urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            token_result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        print(f"ERROR getting token ({exc.code}): {error_body}")
        return 1

    access_token = token_result["access_token"]
    expires_in = token_result.get("expires_in", "unknown")
    print(f"Access token received! (expires in {int(expires_in) // 86400 if expires_in.isdigit() else 'unknown'} days)\n")

    # Step 3: Fetch person URN using /v2/userinfo (OpenID Connect)
    print("Fetching your LinkedIn person URN using /v2/userinfo...")

    me_req = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        with urllib.request.urlopen(me_req, timeout=30) as resp:
            me = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        print(f"ERROR fetching profile ({exc.code}): {error_body}")
        print("Falling back to /v2/me...")
        return fallback_to_me_endpoint(access_token)

    # /v2/userinfo returns 'sub' as the person ID
    if "sub" not in me:
        print("ERROR: 'sub' field not found in /v2/userinfo response.")
        print("Response:", json.dumps(me, indent=2))
        return 1

    person_urn = f"urn:li:person:{me['sub']}"
    name = me.get("name", me.get("given_name", "") + " " + me.get("family_name", "")).strip()

    print(f"\nHello, {name}!")
    print("=" * 60)
    print("YOUR LINKEDIN CREDENTIALS (add as GitHub Secrets):")
    print("=" * 60)
    print(f"\nLINKEDIN_ACCESS_TOKEN:")
    print(f"{access_token}\n")
    print(f"LINKEDIN_PERSON_URN:")
    print(f"{person_urn}\n")
    print("=" * 60)
    print("Add these to your GitHub repo:")
    print("Settings → Secrets and variables → Actions → New repository secret")
    print("=" * 60)
    print("\nAfter adding the secrets, comment 'approve' on any")
    print("LinkedIn Post issue to auto-post to your account.")

    return 0


def fallback_to_me_endpoint(access_token: str) -> int:
    """Fallback to /v2/me if /v2/userinfo fails."""
    me_req = urllib.request.Request(
        "https://api.linkedin.com/v2/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        with urllib.request.urlopen(me_req, timeout=30) as resp:
            me = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        print(f"ERROR fetching profile from /v2/me ({exc.code}): {error_body}")
        return 1

    person_id = me.get("id")
    if not person_id:
        print("ERROR: 'id' field not found in /v2/me response.")
        print("Response:", json.dumps(me, indent=2))
        return 1

    person_urn = f"urn:li:person:{person_id}"
    name = f"{me.get('localizedFirstName', '')} {me.get('localizedLastName', '')}".strip()

    print(f"\nHello, {name}!")
    print("=" * 60)
    print("YOUR LINKEDIN CREDENTIALS (add as GitHub Secrets):")
    print("=" * 60)
    print(f"\nLINKEDIN_ACCESS_TOKEN:")
    print(f"{access_token}\n")
    print(f"LINKEDIN_PERSON_URN:")
    print(f"{person_urn}\n")
    print("=" * 60)
    print("Add these to your GitHub repo:")
    print("Settings → Secrets and variables → Actions → New repository secret")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())