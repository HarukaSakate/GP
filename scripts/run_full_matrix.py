#!/usr/bin/env python3
"""Run the complete CC/ABR/TCP-signal/netem matrix with headless Chrome."""

from __future__ import annotations

import argparse
import json
import os
import queue
import random
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path


CCS = ("cubic", "bbr")
ABRS = ("throughput", "bola")
SIGNALS = (
    ("none", False, False, False),
    ("rtt", True, False, False),
    ("cwnd", False, True, False),
    ("loss", False, False, True),
    ("rtt-cwnd", True, True, False),
    ("rtt-loss", True, False, True),
    ("cwnd-loss", False, True, True),
    ("rtt-cwnd-loss", True, True, True),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", default="experiments/netem_profiles.json")
    parser.add_argument("--results-dir", default="results/full-matrix-r01")
    parser.add_argument("--image", default="gp-experiment:latest")
    parser.add_argument("--media-dir", default=str(Path(__file__).resolve().parents[1] / "dash/test2"))
    parser.add_argument("--http-port", type=int, default=18000)
    parser.add_argument("--ws-port", type=int, default=18765)
    parser.add_argument("--debug-port", type=int, default=19222)
    parser.add_argument("--timeout-sec", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--only", help="Run one condition id (for smoke testing)")
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--max-attempts", type=int, default=15)
    parser.add_argument("--disable-custom-rule", action="store_true")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    return parser.parse_args()


@dataclass(frozen=True)
class Condition:
    cc: str
    abr: str
    signals: str
    rtt: bool
    cwnd: bool
    loss: bool
    profile: dict

    @property
    def condition_id(self) -> str:
        return f"cc-{self.cc}_abr-{self.abr}_signals-{self.signals}_netem-{self.profile['name']}"


class ChromePipe:
    def __init__(self, debug_port: int) -> None:
        import websocket

        self.debug_port = debug_port
        self.proc = subprocess.Popen(
            [
                "google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
                "--disable-dev-shm-usage", "--mute-audio",
                "--autoplay-policy=no-user-gesture-required",
                f"--remote-debugging-port={self.debug_port}",
                "--remote-allow-origins=*",
                "--user-data-dir=/tmp/gp-chrome-profile-" + str(time.time_ns()), "about:blank",
            ],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        version_url = f"http://127.0.0.1:{self.debug_port}/json/version"
        wait_http(version_url)
        version = json.loads(urllib.request.urlopen(version_url, timeout=2).read())
        self.socket = websocket.create_connection(
            version["webSocketDebuggerUrl"], timeout=35,
            origin=f"http://127.0.0.1:{self.debug_port}",
        )
        self.next_id = 1
        self.messages: queue.Queue[dict] = queue.Queue()
        self.pending: dict[int, queue.Queue[dict]] = {}
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        created = self.call("Target.createTarget", {"url": "about:blank"})
        attached = self.call(
            "Target.attachToTarget", {"targetId": created["targetId"], "flatten": True}
        )
        self.session_id = attached["sessionId"]
        self.call("Runtime.enable", session=True)
        self.call("Page.enable", session=True)

    def _read(self) -> None:
        while True:
            try:
                raw = self.socket.recv()
            except Exception:
                return
            if not raw:
                return
            message = json.loads(raw)
            request_id = message.get("id")
            if request_id in self.pending:
                self.pending[request_id].put(message)
            else:
                self.messages.put(message)

    def call(self, method: str, params: dict | None = None, session: bool = False) -> dict:
        request_id = self.next_id
        self.next_id += 1
        response_queue: queue.Queue[dict] = queue.Queue()
        self.pending[request_id] = response_queue
        request = {"id": request_id, "method": method, "params": params or {}}
        if session:
            request["sessionId"] = self.session_id
        self.socket.send(json.dumps(request))
        response = response_queue.get(timeout=30)
        self.pending.pop(request_id, None)
        if "error" in response:
            raise RuntimeError(f"CDP {method}: {response['error']}")
        return response.get("result", {})

    def evaluate(self, expression: str, await_promise: bool = False):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
            session=True,
        )
        remote = result.get("result", {})
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return remote.get("value")

    def close(self) -> None:
        try:
            self.call("Browser.close")
        except Exception:
            self.proc.terminate()
        try:
            self.socket.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def wait_http(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(f"server did not become ready: {url}")


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=check, text=True, capture_output=True)


def start_server(
    name: str, cc: str, image: str, http_port: int, ws_port: int, media_dir: Path
) -> None:
    docker("rm", "-f", name, check=False)
    result = docker(
        "run", "-d", "--name", name, "--cap-add", "NET_ADMIN",
        "--sysctl", f"net.ipv4.tcp_congestion_control={cc}",
        "-v", f"{media_dir}:/app/dash/test2:ro",
        "-p", f"{http_port}:8000", "-p", f"{ws_port}:8765", image,
        "python", "scripts/tcp_info_signal_server.py", "--host", "0.0.0.0",
        "--serve-dir", "/app", "--collector", "tcp_info", "--cc", "auto",
    )
    if not result.stdout.strip():
        raise RuntimeError("docker did not return a container id")


def apply_profile(container: str, profile: dict, seed: int) -> None:
    docker(
        "exec", container, "scripts/netem_control.sh", "apply", "eth0",
        profile["rate"], profile["delay"], profile["jitter"], profile["loss"], str(seed),
    )


def write_log_checkpoint(output: Path, logs: list[dict]) -> None:
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(logs, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output)


def output_is_complete(output: Path) -> bool:
    try:
        records = json.loads(output.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return any(record.get("event") in {
        "PLAYBACK_ENDED"
    } for record in records)


def browser_reported_completion(state: dict | None) -> bool:
    """dash.js can finish a static MPD while native video.ended stays false."""
    return bool(state and state.get("playbackEnded"))


def run_browser(
    condition: Condition, http_port: int, ws_port: int, debug_port: int,
    timeout: int, output: Path, disable_custom_rule: bool = False,
) -> tuple[list[dict], bool, str | None]:
    chrome = ChromePipe(debug_port)
    try:
        url = f"http://127.0.0.1:{http_port}/web/player.html"
        chrome.call("Page.navigate", {"url": url}, session=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if chrome.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.2)
        else:
            raise TimeoutError("player page did not load")

        abr_value = "abrThroughput" if condition.abr == "throughput" else "abrBola"
        session_id = "matrix-" + condition.condition_id + "-" + str(time.time_ns())
        expression = f"""
          (() => {{
            window.gpDisableTcpCustomRule = {str(disable_custom_rule).lower()};
            document.getElementById('mpdUrl').value = {json.dumps(f'http://127.0.0.1:{http_port}/dash/test2/stream.mpd')};
            document.getElementById('tcpWsUrl').value = {json.dumps(f'ws://127.0.0.1:{ws_port}')};
            document.getElementById('sessionId').value = {json.dumps(session_id)};
            document.getElementById('abr').value = {json.dumps(abr_value)};
            document.getElementById('tcpAwareMode').value = {json.dumps('off' if condition.signals == 'none' else 'guardrail')};
            document.getElementById('useRttSignal').checked = {str(condition.rtt).lower()};
            document.getElementById('useCwndSignal').checked = {str(condition.cwnd).lower()};
            document.getElementById('useLossSignal').checked = {str(condition.loss).lower()};
            document.getElementById('startBtn').click();
            return true;
          }})()
        """
        chrome.evaluate(expression)

        deadline = time.monotonic() + timeout
        next_checkpoint = 0.0
        last_state = None
        while time.monotonic() < deadline:
            state = chrome.evaluate("""({
              ended: video.ended, playbackEnded: logs.some((item) => item.event === 'PLAYBACK_ENDED'),
              currentTime: video.currentTime,
              duration: video.duration, paused: video.paused,
              readyState: video.readyState, n: logs.length,
              status: statusView.textContent,
              browserError: logs.findLast?.((item) => item.event === 'BROWSER_ERROR') ?? null
            })""")
            last_state = state
            if browser_reported_completion(state):
                chrome.evaluate("addLog({event: 'RUNNER_COMPLETION_OBSERVED', state: " + json.dumps(state) + "})")
                time.sleep(1)
                break
            duration = state.get("duration") if state else None
            current_time = state.get("currentTime") if state else None
            if state and "error" in state.get("status", "").lower():
                raise RuntimeError(f"player error: {state}")
            if state and state.get("browserError"):
                raise RuntimeError(f"browser error: {state['browserError']}")
            if time.monotonic() >= next_checkpoint:
                logs = chrome.evaluate("JSON.parse(JSON.stringify(logs))")
                write_log_checkpoint(output, logs)
                next_checkpoint = time.monotonic() + 10
            time.sleep(2)
        else:
            chrome.evaluate(
                "addLog({event: 'RUNNER_TIMEOUT', timeoutSec: " + str(timeout) +
                ", state: " + json.dumps(last_state) + "})"
            )
            logs = chrome.evaluate("JSON.parse(JSON.stringify(logs))")
            write_log_checkpoint(output, logs)
            return logs, False, f"playback exceeded {timeout}s; state={last_state}"

        logs = chrome.evaluate("JSON.parse(JSON.stringify(logs))")
        write_log_checkpoint(output, logs)
        completed = any(record.get("event") == "PLAYBACK_ENDED" for record in logs)
        return logs, completed, None if completed else "missing PLAYBACK_ENDED record"
    except Exception as exc:
        try:
            chrome.evaluate("addLog({event: 'RUNNER_ERROR', error: " + json.dumps(repr(exc)) + "})")
            logs = chrome.evaluate("JSON.parse(JSON.stringify(logs))")
            write_log_checkpoint(output, logs)
        except Exception:
            pass
        raise
    finally:
        chrome.close()


def main() -> int:
    args = parse_args()
    if not 1 <= args.repetitions <= args.max_attempts:
        raise SystemExit("require 1 <= repetitions <= max-attempts")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("require 0 <= --shard-index < --shard-count")
    profiles = json.loads(Path(args.profiles).read_text())["profiles"]
    media_dir = Path(args.media_dir).resolve()
    required_media = (media_dir / "stream.mpd", media_dir / "init-stream0.m4s")
    if not all(path.is_file() for path in required_media):
        raise SystemExit(f"missing DASH media under {media_dir}")
    if (media_dir / "init-stream0.m4s").read_bytes().startswith(b"version https://git-lfs"):
        raise SystemExit(f"DASH media under {media_dir} contains Git LFS pointers")
    conditions = [
        Condition(cc, abr, label, rtt, cwnd, loss, profile)
        for cc in CCS for abr in ABRS
        for label, rtt, cwnd, loss in SIGNALS
        for profile in profiles
    ]
    if args.only:
        conditions = [item for item in conditions if item.condition_id == args.only]
        if not conditions:
            raise SystemExit(f"unknown --only condition: {args.only}")
    else:
        random.Random(args.seed).shuffle(conditions)
        conditions = conditions[args.shard_index::args.shard_count]

    results_dir = Path(args.results_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)
    # A new batch prevents mixing source versions and overwriting previous trials.
    batch = results_dir / "batch.json"
    if batch.exists():
        raise SystemExit(f"batch already exists: {results_dir}; choose a fresh directory")
    import hashlib
    root = Path(__file__).resolve().parents[1]
    sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
               for folder in ("scripts", "web", "experiments")
               for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    media = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in media_dir.iterdir() if p.is_file()}
    (results_dir / "source.patch").write_text(subprocess.run(["git", "diff", "--binary"], capture_output=True, text=True).stdout)
    batch.write_text(json.dumps({"args": vars(args), "sources": sources, "media": media,
        "image": docker("image", "inspect", args.image).stdout,
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout,
        "dependencies": subprocess.run([os.sys.executable, "-m", "pip", "freeze"],
                                       capture_output=True, text=True).stdout}, indent=2))
    manifest = results_dir / f"manifest-shard-{args.shard_index}.jsonl"
    container = f"gp-matrix-s{args.shard_index}-{os.getpid()}"
    counts = {c.condition_id: 0 for c in conditions}
    attempts = {c.condition_id: 0 for c in conditions}
    rng = random.Random(args.seed)
    try:
        for round_index in range(args.max_attempts):
            pending = [c for c in conditions if counts[c.condition_id] < args.repetitions]
            rng.shuffle(pending)
            for condition in pending:
                key = condition.condition_id
                attempts[key] += 1
                attempt_dir = results_dir / "attempts" / key / f"attempt-{attempts[key]:02d}"
                attempt_dir.mkdir(parents=True, exist_ok=False)
                output = attempt_dir / f"dash_qoe_log_{key}.json"
                print(f"[{round_index+1}] {key} valid={counts[key]} attempt={attempts[key]}", flush=True)
                started = time.time()
                status, error = "failed", None
                evidence = {}
                try:
                    start_server(container, condition.cc, args.image, args.http_port, args.ws_port, media_dir)
                    wait_http(f"http://127.0.0.1:{args.http_port}/web/player.html")
                    trial_seed = args.seed + round_index
                    evidence["netem_seed"] = trial_seed
                    apply_profile(container, condition.profile, trial_seed)
                    evidence["qdisc"] = docker("exec", container, "tc", "-s", "qdisc", "show", "dev", "eth0").stdout
                    evidence["cc"] = docker("exec", container, "cat", "/proc/sys/net/ipv4/tcp_congestion_control").stdout.strip()
                    logs, completed, error = run_browser(condition, args.http_port, args.ws_port,
                        args.debug_port, args.timeout_sec, output, args.disable_custom_rule)
                    samples = [r.get("tcpMetrics", {}) for r in logs if r.get("event") == "TCP_SIGNAL_UPDATE"]
                    valid_tcp = bool(samples) and all(m.get("cc") == condition.cc and m.get("connection_id") for m in samples)
                    if completed and valid_tcp and evidence["cc"] == condition.cc:
                        status = "completed"
                        counts[key] += 1
                        target = results_dir / f"run-{counts[key]:02d}" / output.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        output.rename(target)
                        output = target
                    elif not error:
                        error = "missing completion or real TCP/CC validation failed"
                except Exception as exc:
                    error = repr(exc)
                finally:
                    evidence["container_logs"] = docker("logs", container, check=False).stderr
                    docker("rm", "-f", container, check=False)
                if not output.exists():
                    output.write_text(json.dumps([{"event": "RUNNER_ERROR", "error": error}]))
                record = {"condition": key, "status": status, "error": error,
                    "file": str(output.relative_to(results_dir)), "started_at_epoch": started,
                    "duration_seconds": time.time()-started, "profile": condition.profile,
                    "attempt": attempts[key], "evidence": evidence}
                (attempt_dir / "metadata.json").write_text(json.dumps(record, indent=2))
                with manifest.open("a") as handle:
                    handle.write(json.dumps(record) + "\n")
                if status != "completed":
                    print(f"FAILED {key}: {error}", flush=True)
                    if attempts[key] - counts[key] >= 3:
                        raise RuntimeError(f"three failures for {key}; investigate before continuing")
            if all(n == args.repetitions for n in counts.values()):
                break
    finally:
        docker("rm", "-f", container, check=False)
        (results_dir / "counts.json").write_text(json.dumps({k: {"valid": counts[k],
            "attempts": attempts[k], "failed": attempts[k]-counts[k]} for k in counts}, indent=2))
    return 0 if all(n == args.repetitions for n in counts.values()) else 1



if __name__ == "__main__":
    raise SystemExit(main())
