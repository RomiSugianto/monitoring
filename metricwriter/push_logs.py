#!/usr/bin/env python3
"""
Direct Loki push to Grafana Cloud
pip install requests
"""
import time
import random
import json
import requests
from datetime import datetime, timezone
import os

# Load .env automatically for local/dev runs if python-dotenv is installed.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass

# ── Grafana Cloud Loki credentials (env-based; no committed secrets) ────────────────────────
LOKI_URL = os.getenv("LOKI_REMOTE_WRITE_URL", "http://localhost:3100/loki/api/v1/push")
USERNAME = os.getenv("LOKI_REMOTE_WRITE_USERNAME")
PASSWORD = os.getenv("LOKI_REMOTE_WRITE_PASSWORD")


# ── Push logs to Loki ──────────────────────────────────────
def push_logs(stream_labels, log_lines):
    """
    stream_labels: dict of labels e.g. {"job": "api", "env": "dev"}
    log_lines: list of (timestamp_ns_str, message) tuples
    """
    payload = {
        "streams": [{
            "stream": stream_labels,
            "values": log_lines
        }]
    }
    ca_path = os.getenv("LOKI_CA_CERT_PATH")

    if (USERNAME is None) != (PASSWORD is None):
        raise RuntimeError("LOKI_USERNAME and LOKI_PASSWORD must be set together.")

    req_kwargs = {"verify": ca_path or True}

    # We validated USERNAME/PASSWORD are set together above, so auth is always a (str, str) here.
    auth = (USERNAME, PASSWORD)  # type: ignore[arg-type]

    resp = requests.post(
        LOKI_URL,
        json=payload,
        auth=(USERNAME, PASSWORD),
        headers={"Content-Type": "application/json"},
        verify=ca_path or True,
        timeout=15,
    )


    return resp


# ── Simulate API request logs ──────────────────────────────
ENDPOINTS = ["/api/users", "/api/orders", "/api/products"]
METHODS   = ["GET", "POST", "DELETE"]

def simulate_request():
    endpoint = random.choice(ENDPOINTS)
    method   = random.choice(METHODS)
    status   = "success" if random.random() < 0.9 else "failed"
    code     = 200 if status == "success" else random.choice([400, 500, 503])
    duration = round(random.uniform(10, 2000))  # ms

    log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level":     "INFO" if status == "success" else "ERROR",
        "method":    method,
        "endpoint":  endpoint,
        "status":    status,
        "http_code": code,
        "duration": duration,
        "message":   f"{method} {endpoint} → {code} ({duration}ms)"
    }
    return status, log

# ── Main loop ──────────────────────────────────────────────
print("Pushing logs to Grafana Cloud Loki...")


while True:
    status, log = simulate_request()
    ts_ns = str(time.time_ns())

    labels = {
        "job":      "python-app",
        "env":      "dev",
        "status":   status,
        "endpoint": log["endpoint"]
    }

    resp = push_logs(labels, [[ts_ns, json.dumps(log)]])

    icon = "✓" if status == "success" else "✗"
    print(f"[{resp.status_code}] {icon} {log['message']}")

    if resp.status_code not in (200, 204):
        print(f"  ERROR: {resp.text}")

    time.sleep(2)