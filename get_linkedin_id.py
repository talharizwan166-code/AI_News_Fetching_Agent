"""
Run this script to get your LinkedIn member ID.
It opens LinkedIn in your browser — click Allow, then paste the code it shows you.
"""

import json
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
import os

CLIENT_ID = "779q7nct13yhru"
CLIENT_SECRET =  os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = "https://www.linkedin.com/developers/tools/oauth/redirect"
SCOPES = "openid profile w_member_social"


def main():
    print("=" * 50)
    print("LinkedIn Setup")
    print("=" * 50)

    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": "setup",
        })
    )

    print("\nOpening LinkedIn in your browser...")
    print("Click 'Allow' when prompted.")
    print("After that, LinkedIn will show you an authorization code.\n")
    webbrowser.open(auth_url)

    code = input("Paste the authorization code here: ").strip()

    if not code:
        print("No code entered. Exiting.")
        return

    print("\nExchanging code for access token...")

    token_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }).encode()

    req = urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            token_result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        print(f"ERROR getting token: {exc.code} - {error_body}")
        return

    access_token = token_result["access_token"]
    print("Got access token!")

    print("Fetching your member ID...")

    me_req = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        with urllib.request.urlopen(me_req) as resp:
            me = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode()
        print(f"ERROR fetching profile: {exc.code} - {error_body}")
        return

    person_urn = f"urn:li:person:{me['sub']}"
    name = me.get("name", "")

    print(f"\nHello, {name}!")
    print()
    print("=" * 50)
    print("YOUR LINKEDIN DETAILS:")
    print("=" * 50)
    print(f"\nAccess Token:\n{access_token}")
    print(f"\nPerson URN:\n{person_urn}")
    print()
    print("=" * 50)
    print("Copy these two values and paste them to Claude!")
    print("=" * 50)


if __name__ == "__main__":
    main()
