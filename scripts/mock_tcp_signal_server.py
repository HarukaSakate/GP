#!/usr/bin/env python3
"""Minimal mock WebSocket server for TCP-aware ABR player testing.

This server uses only the Python standard library so it can run in the
current environment without extra dependencies.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


@dataclass
class SessionState:
    session_id: str
    connected_at: float
    client_ip: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mock TCP metrics WebSocket server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--scenario",
        choices=["steady", "congested", "oscillate", "bbr_probe"],
        default="oscillate",
    )
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--cc", choices=["cubic", "bbr"], default="cubic")
    parser.add_argument("--session-id", default="exp-mock")
    return parser.parse_args()


def recv_http_headers(conn: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def parse_headers(raw: bytes) -> Dict[str, str]:
    lines = raw.decode("utf-8", errors="ignore").split("\r\n")
    headers: Dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def websocket_accept(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def perform_handshake(conn: socket.socket) -> None:
    raw = recv_http_headers(conn)
    headers = parse_headers(raw)
    key = headers.get("sec-websocket-key")
    if not key:
        raise ValueError("missing Sec-WebSocket-Key")

    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {websocket_accept(key)}\r\n"
        "\r\n"
    )
    conn.sendall(response.encode("utf-8"))


def recv_exact(conn: socket.socket, nbytes: int) -> bytes:
    data = b""
    while len(data) < nbytes:
        chunk = conn.recv(nbytes - len(data))
        if not chunk:
            raise ConnectionError("connection closed")
        data += chunk
    return data


def recv_ws_frame(conn: socket.socket) -> Optional[str]:
    header = conn.recv(2)
    if not header:
        return None

    b1, b2 = header
    opcode = b1 & 0x0F
    masked = (b2 >> 7) & 1
    length = b2 & 0x7F

    if opcode == 0x8:
        return None

    if length == 126:
        length = struct.unpack("!H", recv_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(conn, 8))[0]

    mask = recv_exact(conn, 4) if masked else b""
    payload = recv_exact(conn, length)

    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

    return payload.decode("utf-8", errors="ignore")


def send_ws_text(conn: socket.socket, message: str) -> None:
    payload = message.encode("utf-8")
    header = bytearray()
    header.append(0x81)

    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))

    conn.sendall(bytes(header) + payload)


def build_metrics(
    scenario: str,
    cc: str,
    session_id: str,
    started_at: float,
    step: int,
) -> Dict[str, object]:
    elapsed = max(0.0, time.time() - started_at)
    phase = elapsed / 3.0

    rtt_min_us = 24000
    base_delivery = 2_600_000

    if scenario == "steady":
        rtt_us = 30000
        retrans_delta = 0
        retrans_rate = 0.0
        delivery_rate = base_delivery
        cwnd_packets = 42
    elif scenario == "congested":
        rtt_us = 62000
        retrans_delta = 1 + (step % 2)
        retrans_rate = 0.03
        delivery_rate = 900_000
        cwnd_packets = 20
    elif scenario == "bbr_probe":
        rtt_us = int(28000 + (12000 * abs(math.sin(phase))))
        retrans_delta = 1 if step % 6 == 0 else 0
        retrans_rate = 0.015 if retrans_delta else 0.0
        delivery_rate = int(1_400_000 + 800_000 * abs(math.sin(phase)))
        cwnd_packets = 28 + int(8 * abs(math.sin(phase)))
    else:
        congestion = math.sin(phase)
        rtt_us = int(30000 + max(0.0, congestion) * 40000)
        retrans_delta = 1 if congestion > 0.55 else 0
        retrans_rate = 0.025 if congestion > 0.55 else 0.0
        delivery_rate = int(2_700_000 - max(0.0, congestion) * 1_700_000)
        cwnd_packets = 44 - int(max(0.0, congestion) * 18)

    cwnd_bytes = cwnd_packets * 1448
    packets_out = max(4, cwnd_packets - 5)

    return {
        "type": "tcp_metrics",
        "version": 1,
        "session_id": session_id,
        "timestamp_ms": int(time.time() * 1000),
        "freshness_ms": 0,
        "transport": "tcp",
        "cc": cc,
        "rtt_us": rtt_us,
        "rtt_min_us": rtt_min_us,
        "cwnd_packets": cwnd_packets,
        "cwnd_bytes": cwnd_bytes,
        "packets_out": packets_out,
        "retransmissions_delta": retrans_delta,
        "retransmission_rate": retrans_rate,
        "packet_loss_rate": retrans_rate,
        "rto_events_delta": 0,
        "delivery_rate_bps": delivery_rate,
    }


def handle_client(conn: socket.socket, addr: tuple[str, int], args: argparse.Namespace) -> None:
    perform_handshake(conn)
    print(f"[server] websocket connected from {addr[0]}:{addr[1]}", flush=True)

    session = SessionState(
        session_id=args.session_id,
        connected_at=time.time(),
        client_ip=addr[0],
    )

    hello = recv_ws_frame(conn)
    if hello:
        try:
            payload = json.loads(hello)
            if payload.get("session_id"):
                session.session_id = str(payload["session_id"])
            if payload.get("client_ip"):
                session.client_ip = str(payload["client_ip"])
            print(f"[server] hello={payload}", flush=True)
        except json.JSONDecodeError:
            print(f"[server] non-json hello={hello!r}", flush=True)

    send_ws_text(
        conn,
        json.dumps(
            {
                "type": "hello_ack",
                "session_id": session.session_id,
                "scenario": args.scenario,
                "cc": args.cc,
            }
        ),
    )

    step = 0
    try:
        while True:
            metrics = build_metrics(
                scenario=args.scenario,
                cc=args.cc,
                session_id=session.session_id,
                started_at=session.connected_at,
                step=step,
            )
            send_ws_text(conn, json.dumps(metrics))
            step += 1
            time.sleep(args.interval_ms / 1000.0)
    except (BrokenPipeError, ConnectionError, OSError):
        print(f"[server] websocket disconnected: {session.session_id}", flush=True)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main() -> int:
    args = parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen()
        print(
            "[server] listening on "
            f"ws://{args.host}:{args.port} "
            f"scenario={args.scenario} cc={args.cc}",
            flush=True,
        )

        while True:
            conn, addr = server.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr, args),
                daemon=True,
            )
            thread.start()


if __name__ == "__main__":
    raise SystemExit(main())
