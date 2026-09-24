#!/usr/bin/env python3
"""TCP_INFO-based signal server scaffold for the TCP-aware dash.js player.

This server has three roles:
1. Serve static DASH assets over HTTP/1.1
2. Observe TCP_INFO from accepted HTTP sockets
3. Publish normalized tcp_metrics snapshots over WebSocket

It is intentionally a scaffold. The session mapping is limited to
"single client / single playback" by client IP, matching the current design.
The emitted schema is collector-neutral so an eBPF collector can replace this
implementation without changing the browser client.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import http.server
import json
import socket
import socketserver
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from ebpf_map_reader import SnapshotNormalizer, read_pinned_map


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class TcpInfo(ctypes.Structure):
    """Partial Linux tcp_info layout used by this scaffold.

    This matches the early/common part of struct tcp_info on Linux and is
    enough for RTT, retransmission and cwnd-oriented signals.
    """

    _fields_ = [
        ("tcpi_state", ctypes.c_uint8),
        ("tcpi_ca_state", ctypes.c_uint8),
        ("tcpi_retransmits", ctypes.c_uint8),
        ("tcpi_probes", ctypes.c_uint8),
        ("tcpi_backoff", ctypes.c_uint8),
        ("tcpi_options", ctypes.c_uint8),
        ("tcpi_snd_rcv_wscale", ctypes.c_uint8),
        ("tcpi_delivery_rate_app_limited", ctypes.c_uint8),
        ("tcpi_rto", ctypes.c_uint32),
        ("tcpi_ato", ctypes.c_uint32),
        ("tcpi_snd_mss", ctypes.c_uint32),
        ("tcpi_rcv_mss", ctypes.c_uint32),
        ("tcpi_unacked", ctypes.c_uint32),
        ("tcpi_sacked", ctypes.c_uint32),
        ("tcpi_lost", ctypes.c_uint32),
        ("tcpi_retrans", ctypes.c_uint32),
        ("tcpi_fackets", ctypes.c_uint32),
        ("tcpi_last_data_sent", ctypes.c_uint32),
        ("tcpi_last_ack_sent", ctypes.c_uint32),
        ("tcpi_last_data_recv", ctypes.c_uint32),
        ("tcpi_last_ack_recv", ctypes.c_uint32),
        ("tcpi_pmtu", ctypes.c_uint32),
        ("tcpi_rcv_ssthresh", ctypes.c_uint32),
        ("tcpi_rtt", ctypes.c_uint32),
        ("tcpi_rttvar", ctypes.c_uint32),
        ("tcpi_snd_ssthresh", ctypes.c_uint32),
        ("tcpi_snd_cwnd", ctypes.c_uint32),
        ("tcpi_advmss", ctypes.c_uint32),
        ("tcpi_reordering", ctypes.c_uint32),
        ("tcpi_rcv_rtt", ctypes.c_uint32),
        ("tcpi_rcv_space", ctypes.c_uint32),
        ("tcpi_total_retrans", ctypes.c_uint32),
        ("tcpi_pacing_rate", ctypes.c_uint64),
        ("tcpi_max_pacing_rate", ctypes.c_uint64),
        ("tcpi_bytes_acked", ctypes.c_uint64),
        ("tcpi_bytes_received", ctypes.c_uint64),
        ("tcpi_segs_out", ctypes.c_uint32),
        ("tcpi_segs_in", ctypes.c_uint32),
        ("tcpi_notsent_bytes", ctypes.c_uint32),
        ("tcpi_min_rtt", ctypes.c_uint32),
        ("tcpi_data_segs_in", ctypes.c_uint32),
        ("tcpi_data_segs_out", ctypes.c_uint32),
        ("tcpi_delivery_rate", ctypes.c_uint64),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TCP_INFO signal server scaffold")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--ws-port", type=int, default=8765)
    parser.add_argument("--serve-dir", default=".")
    parser.add_argument("--poll-ms", type=int, default=500)
    parser.add_argument(
        "--collector", choices=["tcp_info", "ebpf"], default="tcp_info",
        help="Kernel metric source. ebpf reads a pinned sockops map.",
    )
    parser.add_argument("--ebpf-map", default="/sys/fs/bpf/tcp_metrics")
    parser.add_argument("--bpftool", default="bpftool")
    parser.add_argument(
        "--cc",
        choices=["auto", "cubic", "bbr"],
        default="auto",
        help="Use the socket's TCP_CONGESTION value by default; explicit values are test overrides.",
    )
    return parser.parse_args()


@dataclass
class ConnectionState:
    conn_id: str
    client_ip: str
    client_port: int
    server_port: int
    sock: socket.socket
    opened_at: float
    last_seen_at: float
    bytes_acked_last: int = 0
    total_retrans_last: int = 0
    segs_out_last: int = 0
    rtt_min_us: Optional[int] = None
    delivery_rate_bps: int = 0
    retransmission_rate: float = 0.0
    latest_snapshot: Optional[dict] = None
    initialized: bool = False
    sampled_at: Optional[float] = None


@dataclass
class SessionState:
    session_id: str
    client_ip: str
    ws_conn: socket.socket
    connected_at: float
    last_sent_at: float = field(default=0.0)


class SignalRegistry:
    def __init__(self, cc: str, collector: str = "tcp_info"):
        self.cc = cc
        self.collector = collector
        self.lock = threading.Lock()
        self.connections: Dict[str, ConnectionState] = {}
        self.sessions: Dict[str, SessionState] = {}

    def register_http_conn(self, client_ip: str, client_port: int, server_port: int, sock: socket.socket) -> str:
        conn_id = f"{client_ip}:{client_port}->{server_port}:{id(sock)}"
        with self.lock:
            self.connections[conn_id] = ConnectionState(
                conn_id=conn_id,
                client_ip=client_ip,
                client_port=client_port,
                server_port=server_port,
                sock=sock,
                opened_at=time.time(),
                last_seen_at=time.time(),
            )
        return conn_id

    def unregister_http_conn(self, conn_id: str) -> None:
        with self.lock:
            self.connections.pop(conn_id, None)

    def register_session(self, session_id: str, client_ip: str, ws_conn: socket.socket) -> None:
        with self.lock:
            self.sessions[session_id] = SessionState(
                session_id=session_id,
                client_ip=client_ip,
                ws_conn=ws_conn,
                connected_at=time.time(),
            )

    def unregister_session(self, session_id: str) -> None:
        with self.lock:
            self.sessions.pop(session_id, None)

    def snapshot_state(self) -> tuple[Dict[str, ConnectionState], Dict[str, SessionState]]:
        with self.lock:
            return dict(self.connections), dict(self.sessions)

    def update_connection_snapshot(self, conn_id: str, snapshot: dict, bytes_acked: int, total_retrans: int, segs_out: int, rtt_min_us: int, delivery_rate_bps: int, retransmission_rate: float, sampled_at: float) -> None:
        with self.lock:
            state = self.connections.get(conn_id)
            if not state:
                return
            state.latest_snapshot = snapshot
            state.bytes_acked_last = bytes_acked
            state.total_retrans_last = total_retrans
            state.segs_out_last = segs_out
            state.rtt_min_us = rtt_min_us
            state.delivery_rate_bps = delivery_rate_bps
            state.retransmission_rate = retransmission_rate
            state.last_seen_at = time.time()
            state.initialized = True
            state.sampled_at = sampled_at


class TrackingHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, directory: str, registry: SignalRegistry, **kwargs):
        self._registry = registry
        self._directory = directory
        self._conn_id: Optional[str] = None
        super().__init__(*args, directory=directory, **kwargs)

    def setup(self) -> None:
        super().setup()
        client_ip, client_port = self.client_address
        server_port = self.connection.getsockname()[1]
        self._conn_id = self._registry.register_http_conn(
            client_ip=client_ip,
            client_port=client_port,
            server_port=server_port,
            sock=self.connection,
        )

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            if self._conn_id:
                self._registry.unregister_http_conn(self._conn_id)
                self._conn_id = None

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


def make_http_handler(directory: str, registry: SignalRegistry):
    def factory(*args, **kwargs):
        return TrackingHTTPRequestHandler(*args, directory=directory, registry=registry, **kwargs)

    return factory


def parse_headers(raw: bytes) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    lines = raw.decode("utf-8", errors="ignore").split("\r\n")
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def recv_http_headers(conn: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def websocket_accept(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def perform_ws_handshake(conn: socket.socket) -> None:
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


def recv_ws_text(conn: socket.socket) -> Optional[str]:
    header = conn.recv(2)
    if not header:
        return None

    b1, b2 = header
    opcode = b1 & 0x0F
    length = b2 & 0x7F
    masked = (b2 >> 7) & 1

    if opcode == 0x8:
        return None

    if length == 126:
        length = struct.unpack("!H", recv_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(conn, 8))[0]

    mask = recv_exact(conn, 4) if masked else b""
    payload = recv_exact(conn, length)
    if masked:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return payload.decode("utf-8", errors="ignore")


def send_ws_text(conn: socket.socket, message: str) -> None:
    payload = message.encode("utf-8")
    frame = bytearray([0x81])
    length = len(payload)

    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack("!Q", length))

    conn.sendall(bytes(frame) + payload)


def read_tcp_info(sock: socket.socket) -> Optional[TcpInfo]:
    try:
        raw = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, ctypes.sizeof(TcpInfo))
    except OSError:
        return None

    if len(raw) < ctypes.sizeof(TcpInfo):
        return None
    return TcpInfo.from_buffer_copy(raw)


def read_congestion_control(sock: socket.socket, fallback: str = "unknown") -> str:
    """Return the congestion-control algorithm used by this exact socket."""
    tcp_congestion = getattr(socket, "TCP_CONGESTION", 13)
    try:
        raw = sock.getsockopt(socket.IPPROTO_TCP, tcp_congestion, 32)
    except OSError:
        return fallback
    if isinstance(raw, int):
        return fallback
    value = raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip().lower()
    return value or fallback


def select_connection_for_session(connections: Dict[str, ConnectionState], session: SessionState) -> Optional[ConnectionState]:
    candidates = [conn for conn in connections.values() if conn.client_ip == session.client_ip]
    if not candidates:
        return None
    return max(candidates, key=lambda conn: conn.last_seen_at)


def normalize_snapshot(
    state: ConnectionState,
    info: TcpInfo,
    cc: str,
    sample_interval_sec: float,
    session_id: str,
    sampled_at: Optional[float] = None,
) -> tuple[dict, int, int, int, int, int, float, float]:
    sampled_at = time.monotonic() if sampled_at is None else sampled_at
    rtt_us = int(info.tcpi_rtt)
    current_min = int(info.tcpi_min_rtt) if int(info.tcpi_min_rtt) > 0 else rtt_us
    if state.rtt_min_us is not None:
        current_min = min(current_min, state.rtt_min_us)

    total_retrans = int(info.tcpi_total_retrans)
    retrans_delta = max(0, total_retrans - state.total_retrans_last) if state.initialized else 0

    bytes_acked = int(info.tcpi_bytes_acked)
    acked_delta = max(0, bytes_acked - state.bytes_acked_last) if state.initialized else 0
    delivery_rate_bps = int((acked_delta * 8) / sample_interval_sec) if sample_interval_sec > 0 else 0

    if int(info.tcpi_delivery_rate) > 0:
        delivery_rate_bps = int(info.tcpi_delivery_rate) * 8

    segs_out = int(info.tcpi_segs_out)
    segs_out_delta = max(0, segs_out - state.segs_out_last) if state.initialized else 0
    retransmission_rate = 0.0
    if segs_out_delta > 0:
        retransmission_rate = min(1.0, retrans_delta / max(segs_out_delta, 1))

    snapshot = {
        "type": "tcp_metrics",
        "version": 1,
        "session_id": session_id,
        "connection_id": state.conn_id,
        "timestamp_ms": int(time.time() * 1000),
        "freshness_ms": 0,
        "transport": "tcp",
        "cc": cc,
        "rtt_us": rtt_us,
        "rtt_min_us": current_min,
        "cwnd_packets": int(info.tcpi_snd_cwnd),
        "cwnd_bytes": int(info.tcpi_snd_cwnd) * int(info.tcpi_snd_mss),
        "packets_out": int(info.tcpi_unacked),
        "retransmissions_delta": retrans_delta,
        "retransmission_rate": retransmission_rate,
        # TCP retransmissions are used as the observable packet-loss proxy.
        "packet_loss_rate": retransmission_rate,
        "rto_events_delta": int(info.tcpi_retransmits),
        "delivery_rate_bps": max(0, delivery_rate_bps),
        "pacing_rate_bps": max(0, int(info.tcpi_pacing_rate) * 8),
        "app_limited": bool(int(info.tcpi_delivery_rate_app_limited) & 0x1),
    }
    return snapshot, bytes_acked, total_retrans, segs_out, current_min, delivery_rate_bps, retransmission_rate, sampled_at


def collector_loop(registry: SignalRegistry, poll_ms: int) -> None:
    poll_interval_sec = poll_ms / 1000.0

    while True:
        connections, sessions = registry.snapshot_state()

        for session in sessions.values():
            conn = select_connection_for_session(connections, session)
            if not conn:
                continue

            info = read_tcp_info(conn.sock)
            if not info:
                continue

            sampled_at = time.monotonic()
            sample_interval_sec = (
                max(0.001, sampled_at - conn.sampled_at)
                if conn.sampled_at is not None
                else poll_interval_sec
            )
            socket_cc = read_congestion_control(conn.sock, fallback="unknown")
            effective_cc = socket_cc if registry.cc == "auto" else registry.cc
            snapshot, bytes_acked, total_retrans, segs_out, rtt_min_us, delivery_rate_bps, retransmission_rate, sampled_at = normalize_snapshot(
                state=conn,
                info=info,
                cc=effective_cc,
                sample_interval_sec=sample_interval_sec,
                session_id=session.session_id,
                sampled_at=sampled_at,
            )
            registry.update_connection_snapshot(
                conn_id=conn.conn_id,
                snapshot=snapshot,
                bytes_acked=bytes_acked,
                total_retrans=total_retrans,
                segs_out=segs_out,
                rtt_min_us=rtt_min_us,
                delivery_rate_bps=delivery_rate_bps,
                retransmission_rate=retransmission_rate,
                sampled_at=sampled_at,
            )

            try:
                send_ws_text(session.ws_conn, json.dumps(snapshot))
            except OSError:
                registry.unregister_session(session.session_id)

        time.sleep(poll_interval_sec)


def select_ebpf_entry_for_session(entries: list[dict], session: SessionState, http_port: int) -> Optional[dict]:
    """Select the newest server-side DASH socket belonging to a WS client."""
    candidates = [
        entry for entry in entries
        if entry["key"].get("remote_ip") == session.client_ip
        and int(entry["key"].get("local_port", 0)) == http_port
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda entry: int(entry["value"].get("timestamp_ns", 0)))


def ebpf_collector_loop(
    registry: SignalRegistry,
    poll_ms: int,
    map_path: str,
    bpftool: str,
    http_port: int,
) -> None:
    normalizer = SnapshotNormalizer()
    poll_interval_sec = poll_ms / 1000.0
    while True:
        try:
            entries = read_pinned_map(map_path, bpftool=bpftool)
        except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
            print(f"[ebpf] map read failed: {error}", flush=True)
            time.sleep(poll_interval_sec)
            continue

        _, sessions = registry.snapshot_state()
        for session in sessions.values():
            entry = select_ebpf_entry_for_session(entries, session, http_port)
            if not entry:
                continue
            effective_cc = registry.cc if registry.cc != "auto" else "unknown"
            snapshot = normalizer.normalize(entry, session.session_id, effective_cc)
            try:
                send_ws_text(session.ws_conn, json.dumps(snapshot))
            except OSError:
                registry.unregister_session(session.session_id)
        time.sleep(poll_interval_sec)


def ws_session_loop(conn: socket.socket, addr: tuple[str, int], registry: SignalRegistry) -> None:
    session_id = f"anon-{int(time.time() * 1000)}"
    client_ip = addr[0]

    try:
        perform_ws_handshake(conn)
        hello_raw = recv_ws_text(conn)
        if hello_raw:
            try:
                hello = json.loads(hello_raw)
                session_id = str(hello.get("session_id") or session_id)
                client_ip = str(hello.get("client_ip") or client_ip)
            except json.JSONDecodeError:
                pass

        registry.register_session(session_id=session_id, client_ip=client_ip, ws_conn=conn)
        send_ws_text(
            conn,
            json.dumps(
                {
                    "type": "hello_ack",
                    "session_id": session_id,
                    "cc": registry.cc,
                    "collector": registry.collector,
                }
            ),
        )

        while recv_ws_text(conn) is not None:
            pass
    except (ConnectionError, OSError, ValueError):
        pass
    finally:
        registry.unregister_session(session_id)
        try:
            conn.close()
        except OSError:
            pass


def ws_server_loop(host: str, port: int, registry: SignalRegistry) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen()
        print(f"[ws] listening on ws://{host}:{port}", flush=True)

        while True:
            conn, addr = server.accept()
            thread = threading.Thread(
                target=ws_session_loop,
                args=(conn, addr, registry),
                daemon=True,
            )
            thread.start()


def main() -> int:
    args = parse_args()
    serve_dir = str(Path(args.serve_dir).resolve())
    if args.collector == "ebpf" and args.cc == "auto":
        raise SystemExit("--collector ebpf requires --cc cubic or --cc bbr")
    registry = SignalRegistry(cc=args.cc, collector=args.collector)

    collector_thread = threading.Thread(
        target=collector_loop if args.collector == "tcp_info" else ebpf_collector_loop,
        args=(registry, args.poll_ms) if args.collector == "tcp_info" else (
            registry, args.poll_ms, args.ebpf_map, args.bpftool, args.http_port
        ),
        daemon=True,
    )
    collector_thread.start()

    ws_thread = threading.Thread(
        target=ws_server_loop,
        args=(args.host, args.ws_port, registry),
        daemon=True,
    )
    ws_thread.start()

    httpd = ThreadingHTTPServer((args.host, args.http_port), make_http_handler(serve_dir, registry))
    print(
        f"[http] serving {serve_dir} at http://{args.host}:{args.http_port} "
        f"(collector={args.collector}, cc={args.cc}, poll={args.poll_ms}ms)",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] stopping", flush=True)
    finally:
        httpd.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
