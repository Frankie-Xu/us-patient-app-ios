from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.api.runtime import build_local_runtime


class RuntimeCompositionTests(unittest.TestCase):
    def test_local_runtime_is_ready_and_closes_all_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with build_local_runtime(Path(temporary) / "staging") as runtime:
                readiness = runtime.readiness()
                self.assertEqual(readiness["status"], "ready")
                self.assertEqual(
                    set(readiness["checks"]),
                    {
                        "metadata_store",
                        "object_store",
                        "job_queue",
                        "retention_policy",
                        "deletion_coordinator",
                    },
                )
                self.assertTrue(all(readiness["checks"].values()))
            self.assertFalse(runtime.metadata_store.is_ready())
            self.assertFalse(runtime.object_store.is_ready())
            self.assertFalse(runtime.job_queue.is_ready())

    def test_runtime_readiness_fails_closed_when_one_dependency_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = build_local_runtime(Path(temporary) / "staging")
            runtime.object_store.available = False
            readiness = runtime.readiness()
            self.assertEqual(readiness["status"], "not_ready")
            self.assertFalse(readiness["checks"]["object_store"])
            self.assertTrue(readiness["checks"]["metadata_store"])
            runtime.close()


if __name__ == "__main__":
    unittest.main()
