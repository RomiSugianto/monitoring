#!/usr/bin/env python3
"""
Simulate sli:services_status_code:total:1m gauge metric
Mimics ES recording rule behavior → pushes to Grafana Cloud
pip install requests python-snappy
"""
import struct
import time
import random
import requests
import snappy
import os

# Load .env automatically for local/dev runs if python-dotenv is installed.
# In production/CI you should inject env vars directly and the script will still work.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    # python-dotenv is optional.
    pass

# REMOTE_WRITE_URL can be a local receiver or Grafana/Mimir endpoint.
REMOTE_WRITE_URL = os.getenv("PROMETHEUS_REMOTE_WRITE_URL", "http://localhost:9090/api/v1/write")


# Optional basic auth. Do NOT commit real credentials.
REMOTE_WRITE_USERNAME = os.getenv("PROMETHEUS_REMOTE_WRITE_USERNAME")
REMOTE_WRITE_PASSWORD = os.getenv("PROMETHEUS_REMOTE_WRITE_PASSWORD")

# TLS best practice: verify certificates.
REMOTE_WRITE_CA_CERT_PATH = os.getenv("REMOTE_WRITE_CA_CERT_PATH")
DEBUG_REMOTE_WRITE = os.getenv("DEBUG_REMOTE_WRITE", "0") == "1"


# ── Protobuf encoder ───────────────────────────────────────
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
    return tag(f,2) + varint(len(b)) + b

def pb_msg(f, b):  return tag(f,2)+varint(len(b))+b
def pb_f64(f, v):  return tag(f,1)+struct.pack("<d", v)
def pb_i64(f, v):
    if v < 0:
        v += 1 << 64
    return tag(f,0)+varint(v)

def timeseries(labels_dict, value, ts_ms):
    data = b""
    for k, v in sorted(labels_dict.items()):
        data += pb_msg(1, pb_str(1, k) + pb_str(2, v))
    data += pb_msg(2, pb_f64(1, value) + pb_i64(2, ts_ms))
    return data

def push(series_list):
    if (REMOTE_WRITE_USERNAME is None) != (REMOTE_WRITE_PASSWORD is None):
        raise RuntimeError(
            "Both REMOTE_WRITE_USERNAME and REMOTE_WRITE_PASSWORD must be set (or neither)."
        )

    # use clear variable names to avoid ambiguous single-letter identifiers
    data = b"".join(pb_msg(1, timeseries(labels, v, t)) for labels, v, t in series_list)

    req_kwargs = {}
    if REMOTE_WRITE_USERNAME is not None:
        req_kwargs["auth"] = (REMOTE_WRITE_USERNAME, REMOTE_WRITE_PASSWORD)

    # TLS verification: keep verify=True by default.
    # If a CA bundle is provided, use it.
    if REMOTE_WRITE_CA_CERT_PATH:
        req_kwargs["verify"] = REMOTE_WRITE_CA_CERT_PATH
    else:
        req_kwargs["verify"] = True

    resp = requests.post(
        REMOTE_WRITE_URL,
        data=snappy.compress(data),
        headers={
            "Content-Encoding": "snappy",
            "Content-Type": "application/x-protobuf",
            "X-Prometheus-Remote-Write-Version": "0.1.0",
        },
        **req_kwargs,
        timeout=15,
    )

    if DEBUG_REMOTE_WRITE:
        print(f"Remote write URL: {REMOTE_WRITE_URL}")
        print(f"Remote write status: {resp.status_code}")
        if resp.text:
            print(f"Remote write response body: {resp.text[:1000]}")

    return resp


# ── Service simulation config ──────────────────────────────
INTERVAL = 1  # seconds
SERVICES = {
    "payment":      {"base_rps": 15, "error_rate": 0.0002},
    "worker":       {"base_rps": 20, "error_rate": 0.0002},
    "notification": {"base_rps": 10, "error_rate": 0.0002},
    "backend":      {"base_rps": 12, "error_rate": 0.0002},
    "frontend":     {"base_rps": 12, "error_rate": 0.0002},
}

STATUS_CODES = {
    "success": ["200", "201", "204"],
    "client_error": ["400", "401", "403", "404"],
    "server_error": ["500", "502", "503"],
}

STATUS_MAP = {
    code: (
        "success" if group == "success" else "failed"
    )
    for group, codes in STATUS_CODES.items() for code in codes
}

def map_message(service, status_code):
    if status_code in STATUS_CODES["success"]:
        return f"message from {service} with status {status_code}"
    elif status_code in STATUS_CODES["client_error"]:
        return f"client error from {service} with status {status_code}"
    elif status_code in STATUS_CODES["server_error"]:
        return f"server error from {service} with status {status_code}"
    else:
        return f"unknown status from {service} with status {status_code}"

def map_status(status_code: str) -> str:
    return STATUS_MAP.get(status_code, "pending")

def simulate_minute_counts(service, config):
    """
    Returns dict of {status_code: count} for one 1-minute window.
    Mimics what ES bucketAgg count would return.
    """
    base     = config["base_rps"]
    err_rate = config["error_rate"]

    # Add realistic variance (±30%)
    total = int(base * 60 * random.uniform(0.7, 1.3))

    n_server_err = int(total * err_rate * random.uniform(0.01, 0.05))
    n_client_err = int(total * 0.02 * random.uniform(0.01, 0.05))
    n_success    = total - n_server_err - n_client_err

    counts = {}

    # Distribute success across 200/201/204
    counts["200"] = int(n_success * 0.85)
    counts["201"] = int(n_success * 0.10)
    counts["204"] = n_success - counts["200"] - counts["201"]

    # Server errors
    if n_server_err > 0:
        counts["500"] = int(n_server_err * 0.6)
        counts["503"] = n_server_err - counts["500"]

    # Client errors
    if n_client_err > 0:
        counts["400"] = int(n_client_err * 0.5)
        counts["404"] = n_client_err - counts["400"]

    # Remove zeros
    return {k: v for k, v in counts.items() if v > 0}

# ── Main loop — push every 60s (matches 1m eval interval) ──
print("Pushing sli_logwriter_1m gauge...")
print("Interval: 60s | Services:", list(SERVICES.keys()))
print()

while True:
    ts_ms  = int(time.time() * 1000)
    series = []
    report = []

    for service, config in SERVICES.items():
        counts = simulate_minute_counts(service, config)
        total  = sum(counts.values())
        errors = sum(v for k, v in counts.items() if k not in ("200","201","204"))

        for status_code, count in counts.items():
            series.append((
                {
                    "__name__" : "sli_logwriter_1m",
                    "job" : "logwriter",
                    "service" : service,
                    "message" : map_message(service, status_code),
                    "status" : map_status(status_code),
                    "status_code" : status_code,
                    "duration" : str(random.randint(50, 1000)),
                },
                float(count),
                ts_ms
            ))

        report.append(
            f"  {service:<28} total={total:>4}  "
            f"errors={errors:>3}  "
            f"error_rate={errors/total*100:.4f}%"
        )

    resp = push(series)
    print(f"[{resp.status_code}] Pushed {len(series)} series at {time.strftime('%H:%M:%S')}")
    for r in report:
        print(r)

    if resp.status_code not in (200, 204):
        print(f"  ERROR: {resp.text}")

    print()
    time.sleep(INTERVAL)