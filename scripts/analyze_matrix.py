#!/usr/bin/env python3
"""Analyze every manifest attempt; failed attempts remain in failure rates."""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from analyze_results_notc import summarize


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['condition'])
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('batch', type=Path)
    args = parser.parse_args()
    groups = defaultdict(list)
    trials = []
    for manifest in sorted(args.batch.glob('manifest-shard-*.jsonl')):
        for line in manifest.read_text().splitlines():
            m = json.loads(line)
            path = args.batch / m['file']
            logs = json.loads(path.read_text())
            try:
                row = summarize(path)
            except (StopIteration, KeyError):
                row = {}
            heartbeats = [r for r in logs if r.get('event') == 'HEARTBEAT']
            tcp = [r.get('tcpMetrics') for r in heartbeats]
            fresh = [r for r in tcp if r is not None]
            row.update(condition=m['condition'], status=m['status'], file=m['file'],
                       error=m.get('error'), attempt=m['attempt'],
                       missing_tcp_pct=100*sum(r is None for r in tcp)/len(tcp) if tcp else None,
                       tcp_age_mean_ms=statistics.fmean(r.get('ageMs', 0) for r in fresh) if fresh else None,
                       buffer_mean_sec=statistics.fmean(r['bufferLevel'] for r in heartbeats if isinstance(r.get('bufferLevel'), (float,int))) if any(isinstance(r.get('bufferLevel'), (float,int)) for r in heartbeats) else None)
            end = next((r for r in reversed(logs) if r.get('event') == 'PLAYBACK_ENDED'), {})
            row['time_weighted_bitrate_mbps'] = end.get('timeWeightedAvgBitrateBps')/1e6 if isinstance(end.get('timeWeightedAvgBitrateBps'),(float,int)) else None
            groups[m['condition']].append(row)
            trials.append(row)
    # Normalize fields for startup failures with no START record.
    keys = list(dict.fromkeys(k for r in trials for k in r))
    write_csv(args.batch/'trials.csv', [{k:r.get(k) for k in keys} for r in trials])
    summary = []
    metrics = ['startup_sec','stall_sec','stall_count','switch_count','avg_bitrate_mbps',
               'time_weighted_bitrate_mbps','buffer_mean_sec','guardrail_count','rtt_mean_ms',
               'cwnd_mean_packets','loss_mean_pct','missing_tcp_pct','tcp_age_mean_ms']
    for condition, rows in sorted(groups.items()):
        valid = [r for r in rows if r['status'] == 'completed']
        for metric in metrics:
            values = [r[metric] for r in valid if isinstance(r.get(metric),(int,float)) and math.isfinite(r[metric])]
            n = len(values)
            mean = statistics.fmean(values) if n else None
            sd = statistics.stdev(values) if n>1 else None
            # Student t, two-sided 95%; df 1..30, normal approximation after 30.
            t = [None,12.706,4.303,3.182,2.776,2.571,2.447,2.365,2.306,2.262,2.228,2.201,2.179,2.160,2.145,2.131,2.120,2.110,2.101,2.093,2.086,2.080,2.074,2.069,2.064,2.060,2.056,2.052,2.048,2.045,2.042]
            margin = (t[n-1] if n<=31 else 1.96)*sd/math.sqrt(n) if n>1 else None
            summary.append(dict(condition=condition, metric=metric, valid=len(valid), attempts=len(rows),
                failures=len(rows)-len(valid), failure_rate=(len(rows)-len(valid))/len(rows), metric_n=n,
                mean=mean, median=statistics.median(values) if n else None, stddev=sd,
                ci95_low=mean-margin if margin is not None else None, ci95_high=mean+margin if margin is not None else None))
    write_csv(args.batch/'comparison.csv', summary)
    import html
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="%s">'% (40+25*len(groups)), '<rect width="100%" height="100%" fill="white"/>']
    for i,(condition, rows) in enumerate(sorted(groups.items())):
        valid=sum(r['status']=='completed' for r in rows)
        y=30+25*i
        parts += [f'<text x="10" y="{y}" font-size="12">{html.escape(condition)}</text>', f'<rect x="850" y="{y-12}" width="{300*valid/len(rows)}" height="16" fill="#327a56"/>', f'<text x="1160" y="{y}">{valid}/{len(rows)}</text>']
    parts.append('</svg>')
    (args.batch/'completion.svg').write_text('\n'.join(parts))
    print(f'{len(groups)} observed conditions; {sum(r["status"]=="completed" for r in trials)}/{len(trials)} completed attempts')


if __name__ == '__main__':
    main()
