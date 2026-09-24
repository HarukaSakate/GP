#!/usr/bin/env python3
"""Decode the pinned tcp_metrics eBPF map into collector-neutral snapshots."""

from __future__ import annotations

import argparse
import json
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Iterable


KEY_STRUCT = struct.Struct("<QIII4I4I2I4x")
VALUE_STRUCT = struct.Struct("<QQQQQIIIIIIII")


def _raw_bytes(value) -> bytes:
    if isinstance(value, list):
        return bytes(int(item, 0) if isinstance(item, str) else item for item in value)
    if isinstance(value, str):
        return bytes.fromhex(value.replace(" ", ""))
    raise ValueError(f"unsupported bpftool byte encoding: {type(value).__name__}")


def decode_key(raw: bytes) -> dict:
    if len(raw) != KEY_STRUCT.size:
        raise ValueError(f"unexpected key size: {len(raw)}")
    values = KEY_STRUCT.unpack(raw)
    family = values[1]
    if family == socket.AF_INET:
        local_ip = socket.inet_ntop(socket.AF_INET, raw[12:16])
        remote_ip = socket.inet_ntop(socket.AF_INET, raw[16:20])
    elif family == socket.AF_INET6:
        local_ip = socket.inet_ntop(socket.AF_INET6, raw[20:36])
        remote_ip = socket.inet_ntop(socket.AF_INET6, raw[36:52])
    else:
        local_ip = remote_ip = ""
    return {
        "socket_cookie": values[0],
        "family": family,
        "local_ip": local_ip,
        "remote_ip": remote_ip,
        "local_port": values[-2],
        "remote_port": values[-1],
    }


def decode_value(raw: bytes) -> dict:
    if len(raw) != VALUE_STRUCT.size:
        raise ValueError(f"unexpected value size: {len(raw)}")
    values = VALUE_STRUCT.unpack(raw)
    names = (
        "timestamp_ns", "bytes_acked", "bytes_received", "delivery_rate_bps",
        "pacing_rate_bps", "rtt_us", "rtt_min_us", "cwnd_packets",
        "packets_out", "total_retrans", "segs_out", "app_limited", "state",
    )
    return dict(zip(names, values))


def read_pinned_map(path: str, bpftool: str = "bpftool") -> list[dict]:
    result = subprocess.run(
        [bpftool, "-j", "map", "dump", "pinned", path],
        check=True,
        capture_output=True,
        text=True,
    )
    entries = []
    for entry in json.loads(result.stdout):
        entries.append({
            "key": decode_key(_raw_bytes(entry["key"])),
            "value": decode_value(_raw_bytes(entry["value"])),
        })
    return entries


@dataclass
class PreviousCounters:
    total_retrans: int
    segs_out: int


class SnapshotNormalizer:
    def __init__(self):
        self.previous: Dict[int, PreviousCounters] = {}

    def normalize(self, entry: dict, session_id: str, cc: str) -> dict:
        key, value = entry["key"], entry["value"]
        cookie = key["socket_cookie"]
        previous = self.previous.get(cookie)
        retrans_delta = max(0, value["total_retrans"] - previous.total_retrans) if previous else 0
        segs_delta = max(0, value["segs_out"] - previous.segs_out) if previous else 0
        retransmission_rate = retrans_delta / segs_delta if segs_delta else 0.0
        self.previous[cookie] = PreviousCounters(value["total_retrans"], value["segs_out"])
        timestamp_ns = int(value.get("timestamp_ns", 0))
        freshness_ms = max(0, (time.monotonic_ns() - timestamp_ns) // 1_000_000) if timestamp_ns else 0
        return {
            "type": "tcp_metrics",
            "version": 1,
            "session_id": session_id,
            "connection_id": f"ebpf:{cookie}",
            "timestamp_ms": int(time.time() * 1000),
            "freshness_ms": freshness_ms,
            "transport": "tcp",
            "collector": "ebpf_sockops",
            "cc": cc,
            "local_ip": key["local_ip"],
            "remote_ip": key["remote_ip"],
            "local_port": key["local_port"],
            "remote_port": key["remote_port"],
            "rtt_us": value["rtt_us"],
            "rtt_min_us": value["rtt_min_us"],
            "cwnd_packets": value["cwnd_packets"],
            "cwnd_bytes": 0,
            "packets_out": value["packets_out"],
            "retransmissions_delta": retrans_delta,
            "retransmission_rate": retransmission_rate,
            "packet_loss_rate": retransmission_rate,
            "rto_events_delta": 0,
            "delivery_rate_bps": value["delivery_rate_bps"],
            "pacing_rate_bps": value["pacing_rate_bps"],
            "app_limited": bool(value["app_limited"]),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", default="/sys/fs/bpf/tcp_metrics")
    parser.add_argument("--cc", choices=["cubic", "bbr"], required=True)
    parser.add_argument("--session-id", default="ebpf-observer")
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    normalizer = SnapshotNormalizer()
    while True:
        for entry in read_pinned_map(args.map):
            print(json.dumps(normalizer.normalize(entry, args.session_id, args.cc)), flush=True)
        if args.once:
            return 0
        time.sleep(args.interval_ms / 1000)


if __name__ == "__main__":
    raise SystemExit(main())
