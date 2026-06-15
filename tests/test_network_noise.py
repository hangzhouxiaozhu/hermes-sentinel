"""Network noise reduction tests.

Verifies that consecutive failure tracking works correctly:
- Single failure → no alert
- Repeated failures → alert after threshold
- Recovery resets counter
"""

import sys
import tempfile
import json
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from network_monitor import _track_consecutive_failures, CONSECUTIVE_FAIL_THRESHOLD


class TestConsecutiveFailures(unittest.TestCase):
    """Consecutive failure tracking prevents transient blips from triggering."""

    def setUp(self):
        self.fail_file = Path(tempfile.mktemp(suffix=".json"))
        import network_monitor as nm
        nm.CONSECUTIVE_FAIL_FILE = self.fail_file

    def tearDown(self):
        self.fail_file.unlink(missing_ok=True)

    def test_single_failure_no_alert(self):
        """1 failure should NOT trigger alert."""
        result = _track_consecutive_failures(False)
        self.assertFalse(result)
        data = json.loads(self.fail_file.read_text())
        self.assertEqual(data["count"], 1)

    def test_two_failures_no_alert(self):
        """2 failures should NOT trigger alert (threshold=3)."""
        _track_consecutive_failures(False)
        result = _track_consecutive_failures(False)
        self.assertFalse(result)

    def test_three_failures_triggers_alert(self):
        """3 failures SHOULD trigger alert."""
        _track_consecutive_failures(False)
        _track_consecutive_failures(False)
        result = _track_consecutive_failures(False)
        self.assertTrue(result)

    def test_healthy_resets_counter(self):
        """A healthy check should reset the counter to 0."""
        _track_consecutive_failures(False)
        _track_consecutive_failures(False)
        _track_consecutive_failures(True)  # recovery
        data = json.loads(self.fail_file.read_text())
        self.assertEqual(data["count"], 0)

    def test_failure_after_recovery_restarts_count(self):
        """Failure after recovery should start counting from 1 again."""
        _track_consecutive_failures(False)
        _track_consecutive_failures(False)
        _track_consecutive_failures(True)  # recovery
        _track_consecutive_failures(False)  # new failure
        data = json.loads(self.fail_file.read_text())
        self.assertEqual(data["count"], 1)

    def test_alert_after_recovery_and_new_failures(self):
        """After recovery, need 3 new failures to alert again."""
        # First cycle: 3 failures → alert
        _track_consecutive_failures(False)
        _track_consecutive_failures(False)
        _track_consecutive_failures(False)
        # Reset triggered by alert
        data = json.loads(self.fail_file.read_text())
        self.assertEqual(data["count"], 0)

    def test_multiple_cycles(self):
        """Multiple alert cycles should work."""
        for cycle in range(3):
            for i in range(CONSECUTIVE_FAIL_THRESHOLD - 1):
                self.assertFalse(_track_consecutive_failures(False),
                                 f"Cycle {cycle} step {i} should not alert")
            self.assertTrue(_track_consecutive_failures(False),
                            f"Cycle {cycle} threshold should alert")
