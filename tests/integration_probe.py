#!/usr/bin/env python3
"""Standard-library integration probe for HTTP + WebSocket + TCP_INFO."""

import base64
import json
import os
import socket
import struct


def recv_until(sock, marker):
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("connection closed")
        data += chunk
    return data


def send_masked_text(sock, value):
    payload = json.dumps(value).encode()
    mask = os.urandom(4)
    header = bytearray([0x81])
    if len(payload) < 126:
        header.append(0x80 | len(payload))
    else:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", len(payload)))
    header.extend(mask)
    header.extend(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(header)


def recv_text(sock):
    first, second = sock.recv(2)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
    return json.loads(sock.recv(length).decode())


def main():
    http = socket.create_connection(("127.0.0.1", 8000), timeout=3)
    http.sendall(
        b"GET /web/player.html HTTP/1.1\r\nHost: localhost\r\nConnection: keep-alive\r\n\r\n"
    )
    response = recv_until(http, b"\r\n\r\n")
    if b"200 OK" not in response:
        raise RuntimeError("HTTP player request failed")

    ws = socket.create_connection(("127.0.0.1", 8765), timeout=3)
    key = base64.b64encode(os.urandom(16)).decode()
    ws.sendall(
        (
            "GET / HTTP/1.1\r\nHost: localhost:8765\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    handshake = recv_until(ws, b"\r\n\r\n")
    if b"101 Switching Protocols" not in handshake:
        raise RuntimeError("WebSocket handshake failed")

    send_masked_text(ws, {"type": "hello", "session_id": "integration-probe"})
    ack = recv_text(ws)
    metrics = recv_text(ws)

    assert ack["type"] == "hello_ack"
    assert metrics["type"] == "tcp_metrics"
    assert metrics["session_id"] == "integration-probe"
    assert metrics["connection_id"]
    assert metrics["cc"] not in ("", "auto", "unknown")
    assert metrics["rtt_us"] > 0
    assert metrics["cwnd_packets"] > 0
    assert metrics["pacing_rate_bps"] >= 0
    print(json.dumps(metrics, indent=2, sort_keys=True))

    ws.close()
    http.sendall(
        b"GET /web/player.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    )
    while http.recv(4096):
        pass
    http.close()


if __name__ == "__main__":
    main()
