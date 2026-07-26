#!/usr/bin/env python3
"""
Direct Prometheus Remote Write to Grafana Cloud
pip install requests python-snappy
"""
import struct
import time
import random
import requests
import snappy
import os

# Load .env automatically for local/dev runs if python-dotenv is installed.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass

# REMOTE_WRITE_URL can be a local receiver or Grafana/Mimir endpoint.
REMOTE_WRITE_URL = os.getenv("PROMETHEUS_REMOTE_WRITE_URL", "http://localhost:9090/api/v1/write")


# Optional basic auth. Do NOT commit real credentials.
REMOTE_WRITE_USERNAME = os.getenv("PROMETHEUS_REMOTE_WRITE_USERNAME")
REMOTE_WRITE_PASSWORD = os.getenv("PROMETHEUS_REMOTE_WRITE_PASSWORD")

# TLS best practice: verify certificates.
REMOTE_WRITE_CA_CERT_PATH = os.getenv("REMOTE_WRITE_CA_CERT_PATH")
REMOTE_WRITE_SKIP_VERIFY = os.getenv("REMOTE_WRITE_SKIP_VERIFY", "0") in ("1", "true")
DEBUG_REMOTE_WRITE = os.getenv("DEBUG_REMOTE_WRITE", "0") == "1"

INTERVAL = 1

# ── Minimal protobuf encoder ───────────────────────────────
def varint(n):
    buf = b""
    while True:
        b = n & 0x7F 
        n >>= 7
        buf += bytes([b | 0x80]) if n else bytes([b])
        if not n: 
            break
    return buf

def tag(field, wtype): return varint((field << 3) | wtype)
def pb_str(f, s):  
    b = s.encode()
    return tag(f,2)+varint(len(b))+b

def pb_msg(f, b):  return tag(f,2)+varint(len(b))+b
def pb_f64(f, v):  return tag(f,1)+struct.pack("<d", v)
def pb_i64(f, v):
    if v < 0: 
        v += 1 << 64
    return tag(f,0)+varint(v)

def label(name, value):
    return pb_str(1, name) + pb_str(2, value)

def timeseries(labels_dict, value, ts_ms):
    data = b""
    for k, v in sorted(labels_dict.items()):   # must be sorted
        data += pb_msg(1, label(k, v))
    data += pb_msg(2, pb_f64(1, value) + pb_i64(2, ts_ms))
    return data

def write_request(series_list):
    """series_list: [(labels_dict, value, ts_ms), ...]"""
    data = b""
    for labels_dict, value, ts_ms in series_list:
        data += pb_msg(1, timeseries(labels_dict, value, ts_ms))
    return data

# ── Send to Grafana Cloud ──────────────────────────────────
def push(series_list):
    if (REMOTE_WRITE_USERNAME is None) != (REMOTE_WRITE_PASSWORD is None):
        raise RuntimeError(
            "Both REMOTE_WRITE_USERNAME and REMOTE_WRITE_PASSWORD must be set (or neither)."
        )

    payload = write_request(series_list)

    if REMOTE_WRITE_SKIP_VERIFY:
        req_kwargs = {"verify": False}
    elif REMOTE_WRITE_CA_CERT_PATH:
        req_kwargs = {"verify": REMOTE_WRITE_CA_CERT_PATH}
    else:
        req_kwargs = {"verify": True}
    if REMOTE_WRITE_USERNAME is not None:
        req_kwargs["auth"] = (REMOTE_WRITE_USERNAME, REMOTE_WRITE_PASSWORD)

    resp = requests.post(

        REMOTE_WRITE_URL,
        data=snappy.compress(payload),
        headers={
            "Content-Encoding": "snappy",
            "Content-Type": "application/x-protobuf",
            "X-Prometheus-Remote-Write-Version": "0.1.0",
        },
        **req_kwargs,
        timeout=15,
    )
    return resp


# ── Main loop ──────────────────────────────────────────────
ENDPOINTS = ["/api/users", "/api/orders", "/api/products"]

print("Pushing metrics to Grafana Cloud Prometheus...")
counters = {"success": 0, "failed": 0}

while True:
    ts_ms = int(time.time() * 1000)
    endpoint = random.choice(ENDPOINTS)
    status = "success" if random.random() < 0.9 else "failed"
    counters[status] += 1

    series = [
        ({"__name__": "api_requests_total", "status": "success", "endpoint": endpoint, "job": "python-app"},
         float(counters["success"]), ts_ms),

        ({"__name__": "api_requests_total", "status": "failed",  "endpoint": endpoint, "job": "python-app"},
         float(counters["failed"]),  ts_ms),

        ({"__name__": "api_request_duration_seconds", "endpoint": endpoint, "job": "python-app"},
         round(random.uniform(0.01, 2.0), 3), ts_ms),
    ]

    resp = push(series)
    print(f"[{resp.status_code}] {status} | success={counters['success']} failed={counters['failed']}")

    if resp.status_code not in (200, 204):
        print(f"  ERROR: {resp.text}")

time.sleep(INTERVAL)
