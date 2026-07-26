#!/usr/bin/env python3
"""metricwriter.push_metrics_probe

Simulate Blackbox-style probe metrics and push via Prometheus Remote Write.

Metrics:
- probe_success{instance,job,protocol,module}   -> 1 for success, 0 for failure
- probe_duration_seconds{instance,job,protocol,module} -> observed duration (seconds)

This is intended to exercise existing PromQL queries/dashboards that expect
Blackbox Exporter-like metric names/labels.

Env vars (all optional):
- PROMETHEUS_REMOTE_WRITE_URL (default: http://localhost:9090/api/v1/write)
- PROMETHEUS_REMOTE_WRITE_USERNAME / PROMETHEUS_REMOTE_WRITE_PASSWORD (optional basic auth)
- REMOTE_WRITE_CA_CERT_PATH (optional TLS verification CA bundle)
- DEBUG_REMOTE_WRITE (default: 0)

Probe simulation:
- PROBE_TARGETS (comma-separated; default: https://example.com,https://example.org)
- PROBE_INTERVAL_SEC (default: 5)
- PROBE_FAILURE_RATE (default: 0.1)
- PROBE_DURATION_MIN_SEC (default: 0.01)
- PROBE_DURATION_MAX_SEC (default: 2.0)

Blackbox-style labels:
- PROBE_JOB (default: blackbox-prober)
- PROBE_PROTOCOL (default: http)
- PROBE_MODULE (default: http_2xx)

pip install requests python-snappy
"""

import os
import random
import struct
import time

import requests

# python-snappy is optional; remote write prefers Snappy compression.
# If it's not installed, we send uncompressed protobuf payload.
try:
    import snappy  # type: ignore
except Exception:  # pragma: no cover
    snappy = None

# Load .env automatically for local/dev runs if python-dotenv is installed.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass


# ── Remote write configuration ──────────────────────────────
REMOTE_WRITE_URL = os.getenv(
    "PROMETHEUS_REMOTE_WRITE_URL", "http://localhost:9090/api/v1/write"
)

REMOTE_WRITE_USERNAME = os.getenv("PROMETHEUS_REMOTE_WRITE_USERNAME")
REMOTE_WRITE_PASSWORD = os.getenv("PROMETHEUS_REMOTE_WRITE_PASSWORD")
REMOTE_WRITE_CA_CERT_PATH = os.getenv("REMOTE_WRITE_CA_CERT_PATH")
REMOTE_WRITE_SKIP_VERIFY = os.getenv("REMOTE_WRITE_SKIP_VERIFY", "0") in ("1", "true")
DEBUG_REMOTE_WRITE = os.getenv("DEBUG_REMOTE_WRITE", "0") == "1"


# ── Minimal protobuf encoder (same approach as other metricwriter scripts) ─────────

def varint(n: int) -> bytes:
    buf = b""
    while True:
        b = n & 0x7F
        n >>= 7
        buf += bytes([b | 0x80]) if n else bytes([b])
        if not n:
            break
    return buf


def tag(field: int, wtype: int) -> bytes:
    return varint((field << 3) | wtype)


def pb_str(field: int, s: str) -> bytes:
    b = s.encode()
    return tag(field, 2) + varint(len(b)) + b


def pb_msg(field: int, b: bytes) -> bytes:
    return tag(field, 2) + varint(len(b)) + b


def pb_f64(field: int, v: float) -> bytes:
    return tag(field, 1) + struct.pack("<d", v)


def pb_i64(field: int, v: int) -> bytes:
    if v < 0:
        v += 1 << 64
    return tag(field, 0) + varint(v)


def label(name: str, value: str) -> bytes:
    return pb_str(1, name) + pb_str(2, value)


def timeseries(labels_dict: dict, value: float, ts_ms: int) -> bytes:
    data = b""
    for k, v in sorted(labels_dict.items()):
        data += pb_msg(1, label(k, v))
    # field 2: sample
    data += pb_msg(2, pb_f64(1, float(value)) + pb_i64(2, ts_ms))
    return data


def write_request(series_list):
    """series_list: [(labels_dict, value, ts_ms), ...]"""
    data = b""
    for labels_dict, value, ts_ms in series_list:
        data += pb_msg(1, timeseries(labels_dict, value, ts_ms))
    return data


def push(series_list):
    if (REMOTE_WRITE_USERNAME is None) != (REMOTE_WRITE_PASSWORD is None):
        raise RuntimeError(
            "Both PROMETHEUS_REMOTE_WRITE_USERNAME and PROMETHEUS_REMOTE_WRITE_PASSWORD must be set (or neither)."
        )

    payload = write_request(series_list)

    req_kwargs = {}
    if REMOTE_WRITE_USERNAME is not None:
        req_kwargs["auth"] = (REMOTE_WRITE_USERNAME, REMOTE_WRITE_PASSWORD)

    # TLS verification
    if REMOTE_WRITE_SKIP_VERIFY:
        req_kwargs["verify"] = False
    elif REMOTE_WRITE_CA_CERT_PATH:
        req_kwargs["verify"] = REMOTE_WRITE_CA_CERT_PATH
    else:
        req_kwargs["verify"] = True

    compressed = snappy.compress(payload) if snappy is not None else payload

    resp = requests.post(
        REMOTE_WRITE_URL,
        data=compressed,
        headers={
            "Content-Encoding": "snappy",
            "Content-Type": "application/x-protobuf",
            "X-Prometheus-Remote-Write-Version": "0.1.0",
        },
        **req_kwargs,
        timeout=15,
    )
    return resp


# ── Probe simulation configuration ─────────────────────────
PROBE_TARGETS = [
    t.strip()
    for t in os.getenv(
        "PROBE_TARGETS", "https://example.com,https://example.org"
    ).split(",")
    if t.strip()
]

PROBE_INTERVAL_SEC = float(os.getenv("PROBE_INTERVAL_SEC", "5"))
PROBE_FAILURE_RATE = float(os.getenv("PROBE_FAILURE_RATE", "0.1"))
DURATION_MIN_SEC = float(os.getenv("PROBE_DURATION_MIN_SEC", "0.01"))
DURATION_MAX_SEC = float(os.getenv("PROBE_DURATION_MAX_SEC", "2.0"))

PROBE_JOB = os.getenv("PROBE_JOB", "blackbox-prober")
PROBE_PROTOCOL = os.getenv("PROBE_PROTOCOL", "http")
PROBE_MODULE = os.getenv("PROBE_MODULE", "http_2xx")


# ── Main loop ──────────────────────────────────────────────
print("Pushing probe metrics to Grafana Cloud Prometheus (remote write)...")
print(f"Remote write URL: {REMOTE_WRITE_URL}")
print(f"Targets: {PROBE_TARGETS}")
print(
    f"Labels: job={PROBE_JOB}, protocol={PROBE_PROTOCOL}, module={PROBE_MODULE}"
)
print(f"Interval: {PROBE_INTERVAL_SEC}s | Failure rate: {PROBE_FAILURE_RATE}")

while True:
    ts_ms = int(time.time() * 1000)

    instance = random.choice(PROBE_TARGETS)

    success = random.random() >= PROBE_FAILURE_RATE
    success_val = 1.0 if success else 0.0

    # Emit a duration even on failure (blackbox exporter does); dashboards may use it.
    duration = random.uniform(DURATION_MIN_SEC, DURATION_MAX_SEC)

    labels = {
        "instance": instance,
        "job": PROBE_JOB,
        "protocol": PROBE_PROTOCOL,
        "module": PROBE_MODULE,
    }

    series = [
        (dict(labels, __name__="probe_success"), success_val, ts_ms),
        (dict(labels, __name__="probe_duration_seconds"), float(duration), ts_ms),
    ]

    resp = push(series)

    if DEBUG_REMOTE_WRITE:
        print(f"[{resp.status_code}] instance={instance} success={success_val} duration={duration:.3f}s")
        if resp.text:
            print(resp.text[:1000])
    else:
        print(
            f"[{resp.status_code}] instance={instance} success={int(success_val)} duration={duration:.3f}s"
        )

    if resp.status_code not in (200, 204):
        print(f"  ERROR: {resp.text}")

    time.sleep(PROBE_INTERVAL_SEC)

