#!/usr/bin/env python3
"""Aggregate results_NoTC logs and create CSV/SVG outputs."""

import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results_NoTC"


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def average(values):
    clean = [value for value in values if value is not None]
    return statistics.fmean(clean) if clean else None


def percentile(values, fraction):
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    position = (len(clean) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return clean[low]
    return clean[low] * (high - position) + clean[high] * (position - low)


def summarize(path):
    records = json.loads(path.read_text())
    start = next(record for record in records if record.get("event") == "START")
    endings = [record for record in records if record.get("event") == "PLAYBACK_ENDED"]
    end = endings[-1] if endings else {}
    abr = "BOLA" if start.get("abr") == "abrBola" else "Throughput"
    selected = start.get("tcpSignalsUsed") or {}
    signals = [label for key, label in (("rtt", "RTT"), ("cwnd", "CWND"), ("loss", "Loss")) if selected.get(key)]
    signal_key = "+".join(label.lower() for label in signals) or "none"

    heartbeats = [
        record for record in records
        if record.get("event") == "HEARTBEAT"
        and not record.get("paused") and not record.get("ended")
        and number(record.get("playbackTime")) is not None
    ]
    qualities = [number(record.get("currentQuality")) for record in heartbeats]
    bitrates = [number((record.get("bitrateInfo") or {}).get("bitrate")) for record in heartbeats]
    quality_counts = Counter(int(value) for value in qualities if value is not None)

    metrics = [
        record.get("tcpMetrics") or {} for record in records
        if record.get("event") == "TCP_SIGNAL_UPDATE"
    ]
    cc_values = [str(item.get("cc", "")).upper() for item in metrics if item.get("cc")]
    cc = Counter(cc_values).most_common(1)[0][0] if cc_values else path.parent.name.upper()
    rtt_ms = [number(item.get("rtt_us")) / 1000 for item in metrics if number(item.get("rtt_us")) is not None]
    rttx = []
    for item in metrics:
        current, minimum = number(item.get("rtt_us")), number(item.get("rtt_min_us"))
        if current is not None and minimum is not None and minimum > 0:
            rttx.append(current / minimum)
    cwnds = [number(item.get("cwnd_packets")) for item in metrics]
    peak_cwnd = max((value for value in cwnds if value is not None), default=None)
    losses = [number(item.get("packet_loss_rate", item.get("retransmission_rate"))) for item in metrics]
    retrans = [number(item.get("retransmissions_delta")) for item in metrics]
    guardrails = sum(record.get("event") == "TCP_GUARDRAIL_APPLIED" for record in records)

    stall_ms, startup_ms = number(end.get("totalStallMs")), number(end.get("startupDelayMs"))
    playback_sec = number(end.get("playbackTime"))
    wall_play_sec = number(end.get("totalPlayTimeMs"))
    wall_play_sec = wall_play_sec / 1000 if wall_play_sec is not None else None
    startup_sec = startup_ms / 1000 if startup_ms is not None else None
    mean_bitrate = average(bitrates)
    return {
        "file": path.name,
        "cc": cc,
        "abr": abr,
        "signals": signal_key,
        "condition": abr + " / " + ("+".join(signals) if signals else "None"),
        "completed": bool(endings),
        "playback_sec": playback_sec,
        "wall_play_sec": wall_play_sec,
        "startup_sec": startup_sec,
        "excess_sec": max(0, wall_play_sec - playback_sec - startup_sec)
        if wall_play_sec is not None and playback_sec is not None and startup_sec is not None
        else None,
        "stall_sec": stall_ms / 1000 if stall_ms is not None else None,
        "stall_count": end.get("stallCount"),
        "switch_count": end.get("switchCount"),
        "avg_quality": average(qualities),
        "avg_bitrate_mbps": mean_bitrate / 1_000_000 if mean_bitrate is not None else None,
        "q0_pct": quality_counts[0] * 100 / len(qualities) if qualities else None,
        "q1_pct": quality_counts[1] * 100 / len(qualities) if qualities else None,
        "guardrail_count": guardrails,
        "tcp_samples": len(metrics),
        "rtt_mean_ms": average(rtt_ms),
        "rtt_p95_ms": percentile(rtt_ms, 0.95),
        "rttx_mean": average(rttx),
        "rttx_p95": percentile(rttx, 0.95),
        "rtt_over_1_5_pct": sum(value > 1.5 for value in rttx) * 100 / len(rttx) if rttx else None,
        "cwnd_mean_packets": average(cwnds),
        "cwnd_min_packets": min((value for value in cwnds if value is not None), default=None),
        "cwnd_pressure_pct": sum(
            peak_cwnd is not None
            and number(item.get("cwnd_packets")) is not None
            and number(item.get("packets_out")) is not None
            and number(item.get("cwnd_packets")) <= peak_cwnd * 0.6
            and number(item.get("packets_out")) >= number(item.get("cwnd_packets")) * 0.8
            for item in metrics
        ) * 100 / len(metrics) if metrics else None,
        "loss_mean_pct": average(losses) * 100 if average(losses) is not None else None,
        "loss_p95_pct": percentile(losses, 0.95) * 100 if percentile(losses, 0.95) is not None else None,
        "samples_with_retx_pct": sum(value is not None and value > 0 for value in retrans) * 100 / len(retrans) if retrans else None,
    }


FIELDS = [
    "file", "cc", "abr", "signals", "condition", "completed", "playback_sec", "wall_play_sec",
    "startup_sec", "excess_sec", "stall_sec", "stall_count", "switch_count", "avg_quality",
    "avg_bitrate_mbps", "q0_pct", "q1_pct", "guardrail_count", "tcp_samples",
    "rtt_mean_ms", "rtt_p95_ms", "rttx_mean", "rttx_p95", "rtt_over_1_5_pct",
    "cwnd_mean_packets", "cwnd_min_packets", "cwnd_pressure_pct", "loss_mean_pct",
    "loss_p95_pct", "samples_with_retx_pct",
]


def write_svg(rows, svg_path, title):
    width, height, left, top = 1500, 1085, 90, 55
    panels = [
        ("Playback excess time (s)", "excess_sec", "#d07a1f"),
        ("Stall time (s)", "stall_sec", "#a53f2b"),
        ("Average bitrate (Mbps)", "avg_bitrate_mbps", "#2d6a8a"),
        ("Quality switches", "switch_count", "#7768ae"),
        ("TCP guardrail actions", "guardrail_count", "#34785c"),
    ]
    plot_width, panel_height = width - left - 25, 165
    gap, bar_width = plot_width / len(rows), plot_width / len(rows) * 0.68
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<style>text{font-family:Arial,sans-serif;fill:#222}.title{font-size:24px;font-weight:bold}.axis{font-size:12px}.label{font-size:11px}.grid{stroke:#ddd}</style>',
        '<rect width="100%" height="100%" fill="#fffdf7"/>',
        f'<text x="30" y="32" class="title">{title}: TCP signal condition comparison</text>',
    ]
    for panel_index, (title, key, color) in enumerate(panels):
        y0 = top + panel_index * panel_height
        values = [number(row[key]) or 0 for row in rows]
        maximum = max(values) or 1
        parts.append(f'<text x="10" y="{y0 + 18}" class="axis">{title}</text>')
        for tick in range(5):
            value, y = maximum * tick / 4, y0 + 130 - 110 * tick / 4
            parts.append(f'<line x1="{left}" y1="{y}" x2="{width-25}" y2="{y}" class="grid"/>')
            parts.append(f'<text x="{left-8}" y="{y+4}" text-anchor="end" class="axis">{value:.2f}</text>')
        for index, value in enumerate(values):
            x = left + index * gap + (gap - bar_width) / 2
            bar_height = 110 * value / maximum
            y = y0 + 130 - bar_height
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{color}"/>')
            parts.append(f'<text x="{x+bar_width/2:.1f}" y="{y-3:.1f}" text-anchor="middle" class="label">{value:.2f}</text>')
    label_y = top + len(panels) * panel_height + 12
    for index, row in enumerate(rows):
        x = left + index * gap + gap / 2
        label = row["condition"].replace("Throughput", "TP")
        parts.append(f'<text x="{x:.1f}" y="{label_y}" transform="rotate(55 {x:.1f} {label_y})" class="label">{label}</text>')
    parts.append('<text x="30" y="1070" class="axis">TP = Throughput. One run per condition; descriptive comparison only.</text>')
    parts.append("</svg>")
    svg_path.write_text("\n".join(parts))


def write_csv(rows, csv_path):
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    data_dirs = [
        path for path in sorted(RESULTS.iterdir())
        if path.is_dir() and any(path.glob("dash_qoe_log_*.json"))
    ]
    if not data_dirs and any(RESULTS.glob("dash_qoe_log_*.json")):
        data_dirs = [RESULTS]

    all_rows = []
    for data_dir in data_dirs:
        rows = [summarize(path) for path in sorted(data_dir.glob("dash_qoe_log_*.json"))]
        rows.sort(key=lambda row: (row["abr"] == "BOLA", row["signals"].count("+"), row["signals"]))
        csv_path = data_dir / "analysis_summary.csv"
        svg_path = data_dir / "analysis_comparison.svg"
        write_csv(rows, csv_path)
        write_svg(rows, svg_path, data_dir.name)
        all_rows.extend(rows)
        print(f"Wrote {csv_path}")
        print(f"Wrote {svg_path}")

    all_rows.sort(key=lambda row: (row["cc"], row["abr"] == "BOLA", row["signals"].count("+"), row["signals"]))
    combined_path = RESULTS / "analysis_summary_all.csv"
    write_csv(all_rows, combined_path)
    print(f"Wrote {combined_path}")


if __name__ == "__main__":
    main()
