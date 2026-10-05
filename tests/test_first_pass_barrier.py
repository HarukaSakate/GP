import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_reviewed_matrix import initial_pass_complete, measurement_phase_ready

class FirstPassBarrierTests(unittest.TestCase):
    def test_one_approved_condition_cannot_repeat_while_another_is_untried(self):
        jobs={'first':{'stage':'awaiting_review'},'untried':{'stage':'queued'}}
        with patch('run_reviewed_matrix.approved_review',return_value=True):
            self.assertFalse(initial_pass_complete(jobs))
            self.assertFalse(measurement_phase_ready(jobs,Path('/unused')))
    def test_unreviewed_condition_blocks_repetitions_after_all_first_trials(self):
        jobs={'first':{'stage':'awaiting_review'},'second':{'stage':'awaiting_review'}}
        with patch('run_reviewed_matrix.approved_review',side_effect=[True,False]):
            self.assertTrue(initial_pass_complete(jobs))
            self.assertFalse(measurement_phase_ready(jobs,Path('/unused')))
    def test_repetitions_require_all_first_trials_and_all_reviews(self):
        jobs={'first':{'stage':'awaiting_review'},'second':{'stage':'awaiting_review'}}
        with patch('run_reviewed_matrix.approved_review',return_value=True):
            self.assertTrue(measurement_phase_ready(jobs,Path('/unused')))

if __name__=='__main__':unittest.main()
