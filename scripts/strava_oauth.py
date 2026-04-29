"""
One-time Strava OAuth dance. Run locally:
    uv run python scripts/strava_oauth.py

It prints a URL — open it in a browser, authorize, then paste the FULL redirect URL back.
The script swaps the `code` for access + refresh tokens and prints them so you can paste
into your .env (and into Railway env vars).
"""
import os
import sys
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REDIRECT = "http://localhost/exchange_token"

auth_url = (
    "https://www.strava.com/oauth/authorize"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT}"
    "&response_type=code"
    "&approval_prompt=force"
    "&scope=read,activity:read_all,profile:read_all"
)

print("\n1. Open this URL in your browser:\n")
print(auth_url)
print("\n2. Authorize. Your browser will land on a localhost URL that fails to load — that's fine.")
print("3. Copy the FULL URL from the browser bar and paste it here:\n")

url = input("> ").strip()
qs = parse_qs(urlparse(url).query)
code = qs.get("code", [None])[0]
if not code:
    print("ERROR: no `code` query param in that URL", file=sys.stderr)
    sys.exit(1)

r = requests.post(
    "https://www.strava.com/oauth/token",
    data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    },
    timeout=15,
)
r.raise_for_status()
j = r.json()
print("\nPaste these into your .env (and Railway):\n")
print(f"STRAVA_ACCESS_TOKEN={j['access_token']}")
print(f"STRAVA_REFRESH_TOKEN={j['refresh_token']}")
print(f"\n(athlete: {j.get('athlete', {}).get('firstname')} {j.get('athlete', {}).get('lastname')})")
