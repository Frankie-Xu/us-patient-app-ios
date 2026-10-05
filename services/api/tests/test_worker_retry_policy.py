from __future__ import annotations

import unittest

from scripts.staging.worker import retry_backoff_seconds


class WorkerRetryPolicyTests(unittest.TestCase):
    def test_retry_backoff_is_bounded_and_exponential(self) -> None:
        self.assertEqual(retry_backoff_seconds(0, 1), 0.0)
        self.assertEqual(retry_backoff_seconds(1, 1), 1.0)
        self.assertEqual(retry_backoff_seconds(1, 2), 2.0)
        self.assertEqual(retry_backoff_seconds(1, 4), 8.0)
        self.assertEqual(retry_backoff_seconds(10, 10), 30.0)

    def test_invalid_attempts_do_not_delay(self) -> None:
        self.assertEqual(retry_backoff_seconds(2, 0), 0.0)
        self.assertEqual(retry_backoff_seconds(-1, 1), 0.0)


if __name__ == "__main__":
    unittest.main()
