#!/usr/bin/env python3
"""Run disjoint matrix shards; archive worker evidence and merge successes."""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runner', type=Path, required=True)
    p.add_argument('--profiles', type=Path, required=True)
    p.add_argument('--media-dir', type=Path, required=True)
    p.add_argument('--image', required=True)
    p.add_argument('--results-dir', type=Path, required=True)
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--smoke', action='store_true')
    p.add_argument('--smoke-timeout-sec', type=int, default=90)
    a=p.parse_args()
    if not 1<=a.workers<=3: p.error('workers must be 1..3')
    a.results_dir.mkdir(parents=True, exist_ok=False)
    children=[];handles=[]
    cores=sorted(os.sched_getaffinity(0))
    launch=[]
    conditions=['cc-cubic_abr-throughput_signals-rtt-cwnd-loss_netem-stable-8mbit',
                'cc-bbr_abr-bola_signals-rtt-cwnd-loss_netem-high-rtt-loss',
                'cc-bbr_abr-throughput_signals-none_netem-constrained-2mbit']
    for i in range(a.workers):
        assigned=cores[i::a.workers]
        worker=a.results_dir/f'worker-{i}'
        command=['taskset','-c',','.join(map(str,assigned)),sys.executable,str(a.runner.resolve()),
            '--profiles',str(a.profiles.resolve()),'--media-dir',str(a.media_dir.resolve()),
            '--image',a.image,'--results-dir',str(worker.resolve()),'--seed','20261003',
            '--http-port',str(18100+i),'--ws-port',str(18800+i),'--debug-port',str(19300+i),
            '--shard-count',str(a.workers),'--shard-index',str(i),
            '--repetitions','1' if a.smoke else '10','--max-attempts','3' if a.smoke else '15',
            '--timeout-sec',str(a.smoke_timeout_sec) if a.smoke else '1200']
        if a.smoke:command += ['--only',conditions[i]]
        log=(a.results_dir/f'worker-{i}.log').open('w')
        children.append(subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT))
        handles.append(log);launch.append(dict(worker=i,pid=children[-1].pid,command=command,cpu_affinity=assigned))
    (a.results_dir/'launch.json').write_text(json.dumps(launch,indent=2))
    next_report=0
    profiles=json.loads(a.profiles.read_text())["profiles"]
    expected=conditions[:a.workers] if a.smoke else [f"cc-{cc}_abr-{abr}_signals-{signal}_netem-{profile['name']}" for cc in ["cubic","bbr"] for abr in ["throughput","bola"] for signal in ["none","rtt","cwnd","loss","rtt-cwnd","rtt-loss","cwnd-loss","rtt-cwnd-loss"] for profile in profiles]
    try:
        while True:
            merged=[]
            for i in range(a.workers):
                worker=a.results_dir/f'worker-{i}'
                for f in worker.glob('manifest-shard-*.jsonl'):
                    for line in f.read_text().splitlines():
                        try:r=json.loads(line)
                        except json.JSONDecodeError:continue
                        source=worker/r['file']
                        if r['status']=='completed':
                            target=a.results_dir/r['file']
                            target.parent.mkdir(parents=True,exist_ok=True)
                            if not target.exists():os.link(source,target)
                            r['worker']=i
                        else:r['file']=f'worker-{i}/'+r['file'];r['worker']=i
                        merged.append(r)
            manifest=a.results_dir/'manifest-shard-0.jsonl'
            temp=manifest.with_suffix('.tmp')
            temp.write_text(''.join(json.dumps(r)+'\n' for r in merged));temp.replace(manifest)
            counts=Counter(r['condition'] for r in merged if r['status']=='completed')
            active=[]
            for i,c in enumerate(children):
                detail=dict(worker=i,pid=c.pid,exit_code=c.poll())
                for log in (a.results_dir/f"worker-{i}").glob("attempts/*/*/dash_qoe_log_*.json"):
                    if (log.parent/"metadata.json").exists():continue
                    try:records=json.loads(log.read_text())
                    except (OSError,json.JSONDecodeError):continue
                    hb=[r for r in records if r.get("event")=="HEARTBEAT"]
                    metrics=[r.get("tcpMetrics",{}) for r in records if r.get("event")=="TCP_SIGNAL_UPDATE"]
                    detail.update(condition=log.parent.parent.name,playback_sec=hb[-1].get("playbackTime") if hb else None,tcp_samples=len(metrics),observed_cc=sorted({m.get("cc","") for m in metrics}))
                active.append(detail)
            with (a.results_dir/"condition-coverage.csv").open("w",newline="") as f:
                writer=csv.writer(f);writer.writerow(["condition","valid","total_attempts","failures","required_valid"])
                for key in expected:
                    attempts=[r for r in merged if r["condition"]==key]
                    writer.writerow([key,counts[key],len(attempts),sum(r["status"]!="completed" for r in attempts),1 if a.smoke else 10])
            status={'timestamp':time.strftime('%Y-%m-%d %H:%M:%S'),
                'valid':sum(counts.values()),'required':a.workers if a.smoke else 960,
                'finished_attempts':len(merged),'failures':sum(r['status']!='completed' for r in merged),
                'conditions_with_10':sum(n>=10 for n in counts.values()),
                'workers':active}
            (a.results_dir/'progress.json').write_text(json.dumps(status,indent=2))
            if time.monotonic()>=next_report:
                text=json.dumps(status,ensure_ascii=False)
                print(text,flush=True)
                with (a.results_dir/'progress-5min.jsonl').open('a') as f:f.write(text+'\n')
                next_report=time.monotonic()+300
            analyzer=a.runner.with_name('analyze_matrix.py')
            subprocess.run([sys.executable,str(analyzer),str(a.results_dir)],stdout=subprocess.DEVNULL,check=False)
            if all(c.poll() is not None for c in children):break
            # A stopped worker can bias remaining runs via reduced shared load.
            if any(c.poll() not in (None,0) for c in children):
                raise RuntimeError('worker failed; stop this batch and investigate')
            time.sleep(10)
        return 0 if all(c.returncode==0 for c in children) else 1
    finally:
        for c in children:
            if c.poll() is None:c.send_signal(2)
        for c in children:
            try:c.wait(timeout=45)
            except subprocess.TimeoutExpired:c.terminate()
        for h in handles:h.close()

if __name__=='__main__':sys.exit(main())
