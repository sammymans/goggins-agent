"""
Manually trigger the agent to send an SMS, end-to-end.
Run while the server is running locally (or hit Railway):
    uv run python scripts/test_sms.py [--prerecorded]
"""
import os
import sys

import requests

base = os.environ.get("BASE_URL", "http://localhost:8000")
prerecorded = "--prerecorded" in sys.argv

r = requests.post(f"{base}/trigger", params={"type": "sms", "prerecorded": prerecorded}, timeout=60)
print(r.status_code, r.json())
