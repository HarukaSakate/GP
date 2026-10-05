#!/usr/bin/env python3
"""All conditions once -> review every condition -> independent ten-run batches."""
import argparse
import csv
import hashlib
import json
import os
import random
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from run_full_matrix import CCS, ABRS, SIGNALS, Condition
from review_condition import create_review, approved_review


def initial_pass_complete(jobs):
    return bool(jobs) and all(j['stage'] not in ('queued', 'pilots') for j in jobs.values())


def measurement_phase_ready(jobs, results_dir):
    return initial_pass_complete(jobs) and all(
        approved_review(Path(results_dir)/'reviews'/key) for key in jobs)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runner',type=Path,required=True)
    p.add_argument('--profiles',type=Path,required=True)
    p.add_argument('--media-dir',type=Path,required=True)
    p.add_argument('--image',required=True)
    p.add_argument('--results-dir',type=Path,required=True)
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--seed',type=int,default=20261003)
    p.add_argument('--timeout-sec',type=int,default=1200)
    p.add_argument('--only',action='append')
    p.add_argument('--first',action='append')
    p.add_argument('--phase',choices=['pilots','all','measurements'],default='pilots')
    p.add_argument('--import-pilots',type=Path)
    a=p.parse_args()
    if not 1<=a.workers<=3:p.error('workers must be 1..3')
    profiles=json.loads(a.profiles.read_text())['profiles']
    conditions=[Condition(cc,abr,label,rtt,cwnd,loss,profile).condition_id for cc in CCS for abr in ABRS for label,rtt,cwnd,loss in SIGNALS for profile in profiles]
    if a.only:
        if set(a.only)-set(conditions):p.error('unknown condition')
        conditions=list(dict.fromkeys(a.only))
    random.Random(a.seed).shuffle(conditions)
    if a.first:
        if set(a.first)-set(conditions):p.error("unknown --first condition")
        conditions=list(dict.fromkeys(a.first))+[k for k in conditions if k not in a.first]
    a.results_dir.mkdir(parents=True,exist_ok=False)
    (a.results_dir/'plan.json').write_text(json.dumps(dict(args={k:str(v) if isinstance(v,Path) else v for k,v in vars(a).items()},conditions=conditions,
        runner_sha256=hashlib.sha256(a.runner.read_bytes()).hexdigest(),controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),pilot_counts_toward_ten=False),indent=2))
    jobs={k:dict(stage='queued',slot=None,process=None) for k in conditions}
    if a.import_pilots:
        source_root=a.runner.resolve().parents[1]
        actual_image=json.loads(subprocess.check_output(['docker','image','inspect',a.image],text=True))[0]['Id']
        media_hashes={}
        for key in conditions:
            original=a.import_pilots/'pilots'/key
            if not original.exists():continue
            meta=json.loads((original/'batch.json').read_text())
            for name,digest in meta['sources'].items():
                if hashlib.sha256((source_root/name).read_bytes()).hexdigest()!=digest:
                    raise RuntimeError('cannot import different pilot source: '+name)
            for name,digest in meta['media'].items():
                if name not in media_hashes:media_hashes[name]=hashlib.sha256((a.media_dir/name).read_bytes()).hexdigest()
                if media_hashes[name]!=digest:raise RuntimeError('cannot import different pilot media: '+name)
            if actual_image!=json.loads(meta['image'])[0]['Id']:raise RuntimeError('cannot import different pilot image')
            rows=[json.loads(line) for f in original.glob('manifest-shard-*.jsonl') for line in f.read_text().splitlines()]
            if len(rows)!=1:raise RuntimeError('import requires exactly one first attempt per condition')
            target=a.results_dir/'pilots'/key
            shutil.copytree(original,target)
            review_dir=a.results_dir/'reviews'/key
            create_review(target,review_dir)
            old_review=a.import_pilots/'reviews'/key
            for name in ['review.md','decision.json']:
                if (old_review/name).exists():shutil.copy2(old_review/name,review_dir/name)
            jobs[key]=dict(stage='awaiting_review',slot=None,process=None,imported_from=str(original.resolve()))
    if a.phase=='measurements' and not measurement_phase_ready(jobs,a.results_dir):
        raise SystemExit('all conditions require completed first trials and evidence-bound reviews before measurements')
    slots=list(range(a.workers));cores=sorted(os.sched_getaffinity(0))
    def launch(key, stage, slot):
        if stage=='measurements':
            pilot=json.loads((a.results_dir/'pilots'/key/'batch.json').read_text())
            source_root=a.runner.resolve().parents[1]
            for name,digest in pilot['sources'].items():
                if hashlib.sha256((source_root/name).read_bytes()).hexdigest()!=digest:
                    raise RuntimeError('source changed since pilot: '+name)
            for name,digest in pilot['media'].items():
                if hashlib.sha256((a.media_dir/name).read_bytes()).hexdigest()!=digest:
                    raise RuntimeError('media changed since pilot: '+name)
            actual_image=json.loads(subprocess.check_output(['docker','image','inspect',a.image],text=True))[0]['Id']
            if actual_image!=json.loads(pilot['image'])[0]['Id']:
                raise RuntimeError('image changed since pilot')
        folder=a.results_dir/stage/key
        folder.parent.mkdir(parents=True,exist_ok=True)
        command=['taskset','-c',','.join(map(str,cores[slot::a.workers])),sys.executable,str(a.runner.resolve()),
            '--profiles',str(a.profiles.resolve()),'--media-dir',str(a.media_dir.resolve()),'--image',a.image,
            '--results-dir',str(folder.resolve()),'--only',key,'--repetitions','1' if stage=='pilots' else '10',
            '--max-attempts','1' if stage=='pilots' else '15','--seed',str(a.seed),'--timeout-sec',str(a.timeout_sec),
            '--http-port',str(18100+slot),'--ws-port',str(18800+slot),'--debug-port',str(19300+slot),
            '--shard-count',str(a.workers),'--shard-index',str(slot)]
        log=(a.results_dir/f'{key}-{stage}.log').open('w')
        proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        jobs[key]=dict(stage=stage,slot=slot,process=proc,log=log)
    last_measurement_count=-1
    last_pilot_count=-1
    try:
        while True:
            for key,j in jobs.items():
                proc=j.get('process')
                if proc is not None and proc.poll() is not None:
                    j['log'].close();j['exit_code']=proc.returncode;j['process']=None
                    if j['stage']=='pilots':
                        try:create_review(a.results_dir/'pilots'/key,a.results_dir/'reviews'/key)
                        except Exception as exc:
                            folder=a.results_dir/'reviews'/key;folder.mkdir(parents=True,exist_ok=True)
                            (folder/'review.md').write_text(f'# {key}\n\n初回実行/分析失敗。10回に進まない。\n\n{exc!r}\n')
                        j['stage']='awaiting_review'
                    else:j['stage']='completed' if proc.returncode==0 else 'measurement_failed'
                    slots.append(j['slot']);j['slot']=None
            # A global barrier prevents even an approved condition from repeating
            # before every planned condition has had its first trial and review.
            ready=a.phase!='pilots' and measurement_phase_ready(jobs,a.results_dir)
            for slot in sorted(slots.copy()):
                approved=next((k for k,j in jobs.items() if ready and j['stage']=='awaiting_review'),None)
                queued=next((k for k,j in jobs.items() if j['stage']=='queued'),None)
                if approved:slots.remove(slot);launch(approved,'measurements',slot)
                elif queued and a.phase!='measurements':
                    slots.remove(slot);launch(queued,'pilots',slot)
            merged=[];counts={k:dict(valid=0,attempts=0,failed=0) for k in conditions}
            for key in conditions:
                folder=a.results_dir/'measurements'/key
                for f in folder.glob('manifest-shard-*.jsonl'):
                    for line in f.read_text().splitlines():
                        r=json.loads(line);source=folder/r['file'];counts[key]['attempts']+=1
                        if r['status']=='completed':
                            counts[key]['valid']+=1;target=a.results_dir/r['file'];target.parent.mkdir(parents=True,exist_ok=True)
                            if not target.exists():os.link(source,target)
                        else:counts[key]['failed']+=1;r['file']=str(source.relative_to(a.results_dir))
                        merged.append(r)
            temp=a.results_dir/'manifest.tmp';temp.write_text(''.join(json.dumps(r)+'\n' for r in merged));temp.replace(a.results_dir/'manifest-shard-0.jsonl')
            snapshot={k:{x:y for x,y in j.items() if x not in ['process','log']}|counts[k] for k,j in jobs.items()}
            (a.results_dir/'progress.json').write_text(json.dumps(snapshot,indent=2))
            with (a.results_dir/'condition-coverage.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['condition','stage','valid','attempts','failed','required_valid'])
                for k,j in jobs.items():w.writerow([k,j['stage'],counts[k]['valid'],counts[k]['attempts'],counts[k]['failed'],10])
            if merged and len(merged)!=last_measurement_count:
                subprocess.run([sys.executable,str(a.runner.with_name('analyze_matrix.py')),str(a.results_dir)],stdout=subprocess.DEVNULL,check=True)
                last_measurement_count=len(merged)
            first_snapshot={k:dict(attempts=0,valid=0,failed=0) for k in conditions}
            pilot_rows=[]
            for key in conditions:
                for manifest in (a.results_dir/'pilots'/key).glob('manifest-shard-*.jsonl'):
                    for line in manifest.read_text().splitlines():
                        r=json.loads(line);first_snapshot[key]['attempts']+=1
                        first_snapshot[key]['valid']+=int(r['status']=='completed')
                        first_snapshot[key]['failed']+=int(r['status']!='completed')
                        r['file']=str(Path('pilots')/key/r['file']);pilot_rows.append(r)
            with (a.results_dir/'first-pass-coverage.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['condition','first_attempts','first_valid','first_failed','reviewed'])
                for k,v in first_snapshot.items():w.writerow([k,v['attempts'],v['valid'],v['failed'],approved_review(a.results_dir/'reviews'/k)])
            analysis=a.results_dir/'pilot-analysis';analysis.mkdir(exist_ok=True)
            adjusted=[dict(r,file=str(Path('..')/r['file'])) for r in pilot_rows]
            (analysis/'manifest-shard-0.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in adjusted))
            if pilot_rows and len(pilot_rows)!=last_pilot_count:
                subprocess.run([sys.executable,str(a.runner.with_name('analyze_matrix.py')),str(analysis)],stdout=subprocess.DEVNULL,check=True)
                last_pilot_count=len(pilot_rows)
            summary=dict(phase=a.phase,planned_conditions=len(conditions),first_finished=sum(v['attempts']>0 for v in first_snapshot.values()),first_valid=sum(v['valid'] for v in first_snapshot.values()),first_failed=sum(v['failed'] for v in first_snapshot.values()),first_reviewed=sum(approved_review(a.results_dir/'reviews'/k) for k in conditions),measurement_valid=sum(v['valid'] for v in counts.values()),all_first_trials_finished=initial_pass_complete(jobs))
            (a.results_dir/'phase-status.json').write_text(json.dumps(summary,indent=2))
            if a.phase=='pilots' and initial_pass_complete(jobs):
                (a.results_dir/'first-pass-finished.json').write_text(json.dumps(summary,indent=2))
                return 0
            if any(j['stage']=='measurement_failed' for j in jobs.values()):raise RuntimeError('measurement failed; investigate before continuing')
            if all(j['stage']=='completed' for j in jobs.values()):return 0
            # No long run automatically starts from checks, elapsed time, or absence of a reply.
            time.sleep(10)
    finally:
        for j in jobs.values():
            if j.get('process') is not None and j['process'].poll() is None:j['process'].send_signal(signal.SIGINT)
        for j in jobs.values():
            if j.get('process') is not None:
                try:j['process'].wait(timeout=45)
                except subprocess.TimeoutExpired:j['process'].terminate()
            if j.get('log') is not None and not j['log'].closed:j['log'].close()

if __name__=='__main__':sys.exit(main())
