import sys
import unittest
from unittest.mock import patch

from serve import commands, prepare_storage, supervise


class HostingTests(unittest.TestCase):
    def test_recorder_opt_in(self):
        self.assertEqual(len(commands({})), 1)
        self.assertEqual(commands({"RECORDER_ENABLED": "1"})[1][-1], "900")
        with self.assertRaises(ValueError):
            commands({"RECORDER_ENABLED": "1", "RECORDER_INTERVAL": "10"})

    def test_volume_required(self):
        with self.assertRaises(ValueError):
            prepare_storage({"RAILWAY_PROJECT_ID": "test"})
        with self.assertRaises(ValueError):
            prepare_storage({"RAILWAY_PROJECT_ID": "test", "RAILWAY_VOLUME_MOUNT_PATH": "/volume", "LEDGER_DB_PATH": "/tmp/outside.db"})

    def test_child_failure_stops_service(self):
        with patch("serve.signal.signal"):
            self.assertEqual(supervise([[sys.executable, "-c", "pass"]]), 1)
