from __future__ import annotations

from scripts.staging.resilience_smoke import (
    run_idempotency,
    run_large_file_metadata,
    run_retry_and_polling,
)


def test_large_pdf_and_photo_metadata_are_bounded_without_payloads() -> None:
    result = run_large_file_metadata()
    assert result == {"files_checked": 2, "metadata_only": True, "sessions_pending": 2}


def test_transient_failures_resume_with_bounded_retries_and_polling() -> None:
    result = run_retry_and_polling()
    assert result["recovery_status"] == "succeeded"
    assert result["recovery_attempts"] == 3
    assert result["exhausted_status"] == "failed"
    assert result["bounded"] is True


def test_duplicate_content_replays_and_conflicting_idempotency_fails() -> None:
    result = run_idempotency()
    assert result["replayed_same_resource"] is True
    assert result["conflicting_payload_rejected"] is True
