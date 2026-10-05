import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('matrix_runner', Path(__file__).resolve().parents[1]/'scripts/run_full_matrix.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

class CompletionTests(unittest.TestCase):
    def test_only_real_ended_event_counts_as_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'log.json'
            for event, expected in [('RUNNER_COMPLETION_FALLBACK',False),('RUNNER_TIMEOUT',False),('PLAYBACK_ENDED',True)]:
                path.write_text(json.dumps([{'event':event}]))
                self.assertEqual(m.output_is_complete(path), expected)
    def test_logged_dash_completion_without_native_ended(self):
        self.assertTrue(m.browser_reported_completion({"ended":False,"playbackEnded":True}))
        self.assertFalse(m.browser_reported_completion({"ended":False,"playbackEnded":False,"currentTime":596.4,"duration":596.4}))
        self.assertFalse(m.browser_reported_completion(None))

    def test_condition_filename(self):
        c=m.Condition('bbr','bola','rtt-cwnd-loss',True,True,True,{'name':'baseline'})
        self.assertEqual(c.condition_id,'cc-bbr_abr-bola_signals-rtt-cwnd-loss_netem-baseline')

if __name__=='__main__': unittest.main()
