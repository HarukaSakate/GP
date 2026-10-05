#!/usr/bin/env python3
"""Write first-run evidence; require a separate, evidence-bound review decision."""
import hashlib
import json
import statistics
from pathlib import Path
from analyze_results_notc import summarize


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_review(batch, output):
    batch, output = Path(batch), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    attempts = [json.loads(line) for p in batch.glob('manifest-shard-*.jsonl') for line in p.read_text().splitlines()]
    if len(attempts) != 1:
        raise ValueError('pilot must have exactly one attempt; failures must also be reviewed')
    m = attempts[0]
    log = batch / m['file']
    records = json.loads(log.read_text())
    start = next((r for r in records if r.get('event') == 'START'), {})
    ended = [r for r in records if r.get('event') == 'PLAYBACK_ENDED']
    samples = [r.get('tcpMetrics', {}) for r in records if r.get('event') == 'TCP_SIGNAL_UPDATE']
    hb = [r for r in records if r.get('event') == 'HEARTBEAT' and not r.get('paused') and not r.get('ended')]
    key = m['condition']
    cc, tail = key.removeprefix('cc-').split('_abr-', 1)
    abr, tail = tail.split('_signals-', 1)
    signals, network = tail.split('_netem-', 1)
    chosen = start.get('tcpSignalsUsed', {})
    expected = {s: s in signals.split('-') for s in ['rtt', 'cwnd', 'loss']}
    profile = m.get('profile', {})
    evidence = m.get('evidence', {})
    qdisc = evidence.get('qdisc', '').lower()
    expected_rate = profile.get('rate', '').lower().replace('mbit', 'mbit')
    expected_delay = profile.get('delay', '').lower()
    expected_jitter = profile.get('jitter', '').lower()
    loss = profile.get('loss', '')
    checks = dict(
        completed=m['status'] == 'completed' and bool(ended),
        abr_and_signals=start.get('abr') == ('abrBola' if abr == 'bola' else 'abrThroughput') and chosen == expected and start.get('tcpAwareMode') == ('off' if signals == 'none' else 'guardrail'),
        real_cc=bool(samples) and evidence.get('cc') == cc and all(x.get('cc') == cc for x in samples),
        session_mapping=bool(samples) and bool(start.get('sessionId')) and all(x.get('session_id') == start['sessionId'] and x.get('connection_id') for x in samples),
        rendered_quality_bitrate_consistency=all(r.get("currentQuality") is None or (r.get("bitrateInfo") or {}).get("qualityIndex") == r.get("currentQuality") for r in hb),
        media_socket=bool(samples) and all(str(x.get('http_request_path', '')).endswith(('.mpd', '.m4s')) for x in samples) and any(str(x.get('http_request_path', '')).endswith('.m4s') for x in samples),
        network_and_seed=bool(qdisc) and all(x and x in qdisc for x in [expected_rate, expected_delay, expected_jitter]) and (loss == '0%' or ('loss '+loss) in qdisc) and ('seed '+str(evidence.get('netem_seed'))) in qdisc,
        no_runtime_errors=not any(r.get('event') in ['ERROR', 'BROWSER_ERROR', 'RUNNER_ERROR', 'RUNNER_TIMEOUT', 'TCP_SIGNAL_PARSE_ERROR'] for r in records),
        fresh_playback_signal=bool(hb) and any(r.get('tcpMetrics') is not None for r in hb),
        off_has_no_guardrail=signals != 'none' or not any(r.get('event') in ['TCP_GUARDRAIL_APPLIED', 'TCP_GUARDRAIL_RULE_APPLIED'] for r in records),
    )
    try: values = summarize(log)
    except (StopIteration, KeyError): values = {}
    values['no_fresh_playback_pct'] = 100*sum(r.get('tcpMetrics') is None for r in hb)/len(hb) if hb else None
    ages = [r['tcpMetrics']['ageMs'] for r in hb if r.get('tcpMetrics') and isinstance(r['tcpMetrics'].get('ageMs'), (int,float))]
    values['tcp_age_mean_ms'] = statistics.fmean(ages) if ages else None
    values['time_weighted_bitrate_mbps'] = ended[-1].get('timeWeightedAvgBitrateBps', 0)/1e6 if ended else None
    values['guardrail_stats'] = ended[-1].get('guardrailStats') if ended else None
    review = dict(condition=key, log=str(log.resolve()), log_sha256=sha256(log),
        batch=str((batch/'batch.json').resolve()), batch_sha256=sha256(batch/'batch.json'),
        checks=checks, technical_checks_passed=all(checks.values()), values=values, decision='pending')
    (output/'evidence.json').write_text(json.dumps(review, ensure_ascii=False, indent=2))
    text = [f'# 初回考察: {key}', '', '判断: 未レビュー。検査の通過だけでは10回反復を開始しない。', '',
            '| 技術検査 | 結果 |', '| --- | --- |']
    text += [f'| {k} | {"通過" if v else "要調査"} |' for k,v in checks.items()]
    text += ['', '観測値（単独試行）:', '']
    units = {'startup_sec':'秒','stall_sec':'秒','stall_count':'回','switch_count':'回',
             'time_weighted_bitrate_mbps':'Mbps','guardrail_count':'回','rtt_mean_ms':'ms',
             'cwnd_mean_packets':'パケット','loss_mean_pct':'%','no_fresh_playback_pct':'%','tcp_age_mean_ms':'ms'}
    text += [f'- {k}: {values.get(k)} {unit}' for k,unit in units.items()]
    text += ['', f'Guardrail内部統計: `{json.dumps(values.get("guardrail_stats"),ensure_ascii=False)}`', '',
        '観測事実は上記ログと検査結果。品質低下、停止やGuardrail発動があること自体は測定不良とは扱わない。',
        '原因仮説は単独試行から確定しない。TCP信号の効果は同じCC・ABR・netemの信号なし条件と比較して判断する。',
        '高いRTTはnetemの基本遅延以外の待ち時間も含みうるが、キューを原因と断定するには追加の観測が必要。',
        'Guardrailが0回なら、選択信号、連続確認、Watching/Cooldown、最低品質の各抑制条件を確認する。',
        'n=1なので平均的効果、有意差、信頼区間は主張しない。', '',
        f'ログSHA256: `{review["log_sha256"]}`', f'設定SHA256: `{review["batch_sha256"]}`']
    (output/'review.md').write_text('\n'.join(text)+'\n')
    return review


def approved_review(directory):
    directory = Path(directory)
    if not (directory/'evidence.json').exists() or not (directory/'decision.json').exists():
        return False
    evidence = json.loads((directory/'evidence.json').read_text())
    decision = json.loads((directory/'decision.json').read_text())
    return (evidence['technical_checks_passed'] and decision.get('status') == 'approved'
            and bool(decision.get('reason')) and bool(decision.get('reviewer'))
            and decision.get('condition') == evidence['condition']
            and decision.get('log_sha256') == evidence['log_sha256'] == sha256(evidence['log'])
            and decision.get('batch_sha256') == evidence['batch_sha256'] == sha256(evidence['batch']))
