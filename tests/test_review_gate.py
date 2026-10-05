import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from review_condition import create_review, approved_review

class ReviewGateTests(unittest.TestCase):
    def fixture(self, root, path='/dash/test2/chunk-stream0-00001.m4s', stall_ms=0):
        batch=root/'pilot';batch.mkdir();(batch/'batch.json').write_text('{}')
        records=[{'event':'START','sessionId':'s','abr':'abrThroughput','tcpSignalsUsed':{'rtt':False,'cwnd':False,'loss':False},'tcpAwareMode':'off'},
                 {'event':'TCP_SIGNAL_UPDATE','tcpMetrics':{'session_id':'s','connection_id':'c','cc':'cubic','http_request_path':path,'rtt_us':20000,'rtt_min_us':10000}},
                 {'event':'HEARTBEAT','paused':False,'ended':False,'playbackTime':1,'currentQuality':0,'bitrateInfo':{'bitrate':177434,'qualityIndex':0},'tcpMetrics':{'ageMs':10}},
                 {'event':'PLAYBACK_ENDED','playbackTime':20,'totalPlayTimeMs':21000+stall_ms,'startupDelayMs':1000,'totalStallMs':stall_ms,'stallCount':1 if stall_ms else 0,'switchCount':0,'timeWeightedAvgBitrateBps':177434}]
        (batch/'log.json').write_text(json.dumps(records))
        m={'condition':'cc-cubic_abr-throughput_signals-none_netem-baseline','status':'completed','file':'log.json','attempt':1,
           'profile':{'rate':'8mbit','delay':'20ms','jitter':'2ms','loss':'0%'},'evidence':{'cc':'cubic','netem_seed':1,'qdisc':'netem delay 20ms 2ms rate 8Mbit seed 1'}}
        (batch/'manifest-shard-0.jsonl').write_text(json.dumps(m)+'\n')
        review=root/'review';evidence=create_review(batch,review)
        return batch,review,evidence
    def decision(self, directory,evidence):
        (directory/'decision.json').write_text(json.dumps({'condition':evidence['condition'],'status':'approved','reason':'Reviewed exact evidence','reviewer':'test-only', 'log_sha256':evidence['log_sha256'],'batch_sha256':evidence['batch_sha256']}))
    def test_passing_checks_do_not_automatically_start_repetitions(self):
        with tempfile.TemporaryDirectory() as t:
            _,r,e=self.fixture(Path(t));self.assertTrue(e['technical_checks_passed']);self.assertFalse(approved_review(r))
    def test_review_cannot_be_reused_after_log_changes(self):
        with tempfile.TemporaryDirectory() as t:
            b,r,e=self.fixture(Path(t));self.decision(r,e);self.assertTrue(approved_review(r))
            (b/'log.json').write_text('[]');self.assertFalse(approved_review(r))
    def test_ui_socket_prevents_repeat_even_if_marked_approved(self):
        with tempfile.TemporaryDirectory() as t:
            _,r,e=self.fixture(Path(t),path='/web/player.html');self.decision(r,e);self.assertFalse(approved_review(r))
    def test_requested_bitrate_cannot_be_mistaken_for_rendered_quality(self):
        with tempfile.TemporaryDirectory() as t:
            b,r,e=self.fixture(Path(t))
            records=json.loads((b/'log.json').read_text())
            records[2]['bitrateInfo']={'bitrate':1405744,'qualityIndex':1}
            (b/'log.json').write_text(json.dumps(records))
            e=create_review(b,r);self.assertFalse(e['checks']['rendered_quality_bitrate_consistency'])
            self.decision(r,e);self.assertFalse(approved_review(r))
    def test_poor_qoe_is_not_rejected_as_invalid_measurement(self):
        with tempfile.TemporaryDirectory() as t:
            _,r,e=self.fixture(Path(t),stall_ms=20000);self.assertTrue(e['technical_checks_passed']);self.decision(r,e);self.assertTrue(approved_review(r))

if __name__=='__main__':unittest.main()
