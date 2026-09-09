"""
LinkedIn OAuth setup helper.
Run this script to get your access token and person URN.

Usage:
    python setup_linkedin.py
"""

import json
import urllib.request
import urllib.parse
import webbrowser


def main():
    print("=== LinkedIn OAuth Setup ===\n")

    client_id = input("Enter your Client ID: ").strip()
    client_secret = input("Enter your Client Secret: ").strip()

    redirect_uri = "https://www.linkedin.com/developers/tools/oauth/redirect"

    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile w_member_social",
            "state": "setup123",
        })
    )

    print(f"\nOpening browser for authorization...\n")
    print(f"If the browser doesn't open, copy this URL manually:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("After clicking 'Allow', you'll be redirected.")
    print("Copy the FULL URL from the browser address bar and paste it below.\n")
    redirect_url = input("Paste the redirect URL here: ").strip()

    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)

    if "code" not in params:
        print("\nERROR: No authorization code found in the URL.")
        print("Make sure you copied the entire URL from the browser.")
        return

    code = params["code"][0]
    print(f"\nAuthorization code received. Exchanging for access token...\n")

    token_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }).encode()

    req = urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            token_result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        print(f"ERROR getting token: {exc.code} - {error_body}")
        return

    access_token = token_result["access_token"]
    expires_in = token_result.get("expires_in", "unknown")
    print(f"Access token received! (expires in {int(expires_in)//86400} days)\n")

    print("Fetching your LinkedIn person URN...\n")

    me_req = urllib.request.Request(
        "https://api.linkedin.com/v2/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        with urllib.request.urlopen(me_req) as resp:
            me_result = json.loads(resp.read())
        person_id = me_result["id"]
        person_urn = f"urn:li:person:{person_id}"
        name = f"{me_result.get('localizedFirstName', '')} {me_result.get('localizedLastName', '')}"
        print(f"Hello, {name.strip()}!\n")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        print(f"ERROR fetching profile: {exc.code} - {error_body}")
        print("You can find your URN manually later.\n")
        person_urn = "(could not fetch — see error above)"

    print("=" * 50)
    print("Add these as GitHub Secrets in your repo:")
    print("(Settings -> Secrets and variables -> Actions -> New repository secret)")
    print("=" * 50)
    print(f"\nLINKEDIN_ACCESS_TOKEN:\n{access_token}\n")
    print(f"LINKEDIN_PERSON_URN:\n{person_urn}\n")
    print("=" * 50)
    print("Done! After adding the secrets, comment 'approve' on any")
    print("LinkedIn Post issue to auto-post to your account.")


if __name__ == "__main__":
    main()
