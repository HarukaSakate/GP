#!/usr/bin/env python3
"""Repeat commands under reproducible tc/netem network profiles."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/netem_profiles.json")
    parser.add_argument("--interface", required=True, help="Dedicated experiment interface (for example eth0)")
    parser.add_argument("--command", required=True, help="Playback/probe command; profile variables are exported")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--results-dir", default="results/netem")
    parser.add_argument("--sudo", action="store_true", help="Run tc control through sudo")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def control_command(script: Path, sudo: bool, *args: str) -> list[str]:
    return (["sudo"] if sudo else []) + [str(script), *args]


def main() -> int:
    args = parse_args()
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be at least 1")
    config_path = Path(args.config).resolve()
    profiles = json.loads(config_path.read_text())["profiles"]
    script = Path(__file__).with_name("netem_control.sh").resolve()
    results_root = Path(args.results_dir).resolve()
    results_root.mkdir(parents=True, exist_ok=True)
    clear = control_command(script, args.sudo, "clear", args.interface)

    def cleanup(*_unused) -> None:
        if not args.dry_run:
            subprocess.run(clear, check=False)

    signal.signal(signal.SIGINT, lambda *_: (cleanup(), sys.exit(130)))
    signal.signal(signal.SIGTERM, lambda *_: (cleanup(), sys.exit(143)))

    try:
        for profile in profiles:
            required = ("name", "rate", "delay", "jitter", "loss")
            if any(key not in profile for key in required):
                raise ValueError(f"incomplete profile: {profile}")
            apply = control_command(
                script, args.sudo, "apply", args.interface,
                profile["rate"], profile["delay"], profile["jitter"], profile["loss"],
            )
            for repetition in range(1, args.repetitions + 1):
                run_id = f'{profile["name"]}-r{repetition:02d}'
                run_dir = results_root / run_id
                command = shlex.split(args.command)
                if args.dry_run:
                    print(shlex.join(apply))
                    print("env", f"GP_PROFILE={profile['name']}", f"GP_RUN_ID={run_id}", shlex.join(command))
                    continue
                run_dir.mkdir(parents=True, exist_ok=False)
                subprocess.run(apply, check=True)
                started = time.time()
                env = os.environ.copy()
                env.update({
                    "GP_PROFILE": profile["name"], "GP_RUN_ID": run_id,
                    "GP_RESULTS_DIR": str(run_dir),
                })
                with (run_dir / "stdout.log").open("w") as stdout, (run_dir / "stderr.log").open("w") as stderr:
                    result = subprocess.run(command, env=env, stdout=stdout, stderr=stderr, check=False)
                metadata = {
                    "run_id": run_id,
                    "profile": profile,
                    "repetition": repetition,
                    "interface": args.interface,
                    "command": command,
                    "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
                    "duration_seconds": time.time() - started,
                    "exit_code": result.returncode,
                }
                (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
                subprocess.run(clear, check=False)
                if result.returncode:
                    print(f"{run_id}: command failed ({result.returncode})", file=sys.stderr)
                    return result.returncode
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
