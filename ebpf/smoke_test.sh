#!/bin/sh
set -eu

PIN_DIR=/sys/fs/bpf/gp_tcp_metrics_smoke
CGROUP_REL=$(awk -F: '$1 == "0" { print $3 }' /proc/self/cgroup)
CGROUP_PATH="/sys/fs/cgroup${CGROUP_REL}"
PROGRAM_PIN="$PIN_DIR/program"

cleanup() {
    bpftool cgroup detach "$CGROUP_PATH" sock_ops pinned "$PROGRAM_PIN" 2>/dev/null || true
    rm -rf "$PIN_DIR"
}
trap cleanup EXIT INT TERM

if ! mountpoint -q /sys/fs/bpf; then
    mount -t bpf bpf /sys/fs/bpf
fi

make -C /src/ebpf all
cleanup
mkdir -p "$PIN_DIR"
bpftool prog load /src/ebpf/tcp_metrics.bpf.o "$PROGRAM_PIN" \
    type sockops pinmaps "$PIN_DIR"
bpftool cgroup attach "$CGROUP_PATH" sock_ops pinned "$PROGRAM_PIN"

python3 - <<'PY' &
import socket
import threading
import time

listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", 19090))
listener.listen()

def serve():
    conn, _ = listener.accept()
    while conn.recv(65536):
        conn.sendall(b"ack" * 1024)
    conn.close()

thread = threading.Thread(target=serve)
thread.start()
client = socket.create_connection(("127.0.0.1", 19090))
for _ in range(100):
    client.sendall(b"x" * 16384)
    client.recv(3072)
time.sleep(3)
client.shutdown(socket.SHUT_WR)
client.close()
thread.join()
listener.close()
PY
TRAFFIC_PID=$!
sleep 1

MAP_PIN="$PIN_DIR/tcp_metrics"
test -e "$MAP_PIN"
ENTRY_COUNT=$(bpftool -j map dump pinned "$MAP_PIN" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
test "$ENTRY_COUNT" -gt 0
python3 /src/scripts/ebpf_map_reader.py --map "$MAP_PIN" --cc cubic --once \
    > /tmp/ebpf_snapshots.jsonl
test -s /tmp/ebpf_snapshots.jsonl
python3 -c 'import json; rows=[json.loads(line) for line in open("/tmp/ebpf_snapshots.jsonl")]; assert all(row["collector"] == "ebpf_sockops" for row in rows)'

python3 /src/scripts/tcp_info_signal_server.py \
    --host 0.0.0.0 --serve-dir /src --collector ebpf --ebpf-map "$MAP_PIN" --cc cubic &
SERVER_PID=$!
python3 - <<'PY'
import socket
import time
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", 8000), timeout=0.2).close()
        break
    except OSError:
        time.sleep(0.1)
else:
    raise SystemExit("server did not become ready")
PY
python3 /src/tests/integration_probe.py > /tmp/ebpf_websocket_snapshot.json
python3 -c 'import json; row=json.load(open("/tmp/ebpf_websocket_snapshot.json")); assert row["collector"] == "ebpf_sockops"'
kill "$SERVER_PID"
wait "$SERVER_PID" 2>/dev/null || true
wait "$TRAFFIC_PID"
printf 'eBPF sockops + WebSocket smoke test passed: %s map entries\n' "$ENTRY_COUNT"
