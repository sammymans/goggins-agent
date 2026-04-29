"""
Manually trigger the agent to place a phone call, end-to-end.
    uv run python scripts/test_call.py [--prerecorded]
"""
import os
import sys

import requests

base = os.environ.get("BASE_URL", "http://localhost:8000")
prerecorded = "--prerecorded" in sys.argv

r = requests.post(f"{base}/trigger", params={"type": "call", "prerecorded": prerecorded}, timeout=60)
print(r.status_code, r.json())
