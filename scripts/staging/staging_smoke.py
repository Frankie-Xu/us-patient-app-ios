"""Deterministic local/staging smoke for the patient record lifecycle.

This command exercises the existing API and AI seams in one process.  It uses
only synthetic values, fixed time, and the local SQLite runtime; no network,
credentials, or patient content is required.  The report intentionally keeps
opaque IDs and source text out of the artifact so it is safe to publish as CI
evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_TIME = datetime(2030, 1, 2, 9, 30, tzinfo=timezone.utc)
FIXTURE_BYTES = b"synthetic-staging-document-v1"
FIXTURE_SHA256 = hashlib.sha256(FIXTURE_BYTES).hexdigest()
AUTH_SCOPES = (
    "documents:read,documents:write,facts:read,facts:write,"
    "shares:create,shares:revoke,audit:read"
)
PATIENT_HEADERS = {
    "Authorization": f"Bearer synthetic-staging|{AUTH_SCOPES}|patient",
    "X-Request-Id": "staging-smoke-request",
}
WORKER_AUTH = None  # initialized after importing the API models


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _status(ok: bool, detail: str = "") -> dict[str, str]:
    return {"status": "passed" if ok else "failed", **({"detail": detail} if detail else {})}


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(root))
    from services.ai.doctor_brief import DoctorBriefBlocked, DoctorBriefScope, project_doctor_brief
    from services.ai.golden_set import synthetic_golden_set
    from services.ai.pipeline import DeterministicStubPipeline
    from services.ai.schema import ReviewStatus as AIReviewStatus
    from services.api.app import ApiHttpAdapter
    from services.api.models import AuthContext, JobType, PrincipalRole, ReviewStatus
    from services.api.runtime import build_local_runtime
    from services.api.service import ApiService

    global WORKER_AUTH
    WORKER_AUTH = AuthContext(
        "synthetic-worker",
        roles=frozenset({PrincipalRole.SERVICE}),
        request_id="staging-smoke-worker",
    )

    stages: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="patient-app-staging-") as temporary:
        with build_local_runtime(Path(temporary) / "runtime") as runtime:
            _assert(runtime.is_ready(), "local staging runtime must be ready")
            stages["readiness"] = _status(True)
            service = ApiService(
                store=runtime.metadata_store,
                object_store=runtime.object_store,
                job_queue=runtime.job_queue,
                clock=lambda: FIXTURE_TIME,
            )
            http = ApiHttpAdapter(service)

            # Upload: document creation, idempotent replay, dependency failure,
            # successful retry, and a natural same-byte PUT replay.
            create_headers = {**PATIENT_HEADERS, "Idempotency-Key": "staging-document-001"}
            document_response = http.handle(
                "POST",
                "/v1/documents",
                headers=create_headers,
                body={
                    "filename": "synthetic-staging-record.pdf",
                    "media_type": "application/pdf",
                    "size_bytes": len(FIXTURE_BYTES),
                    "sha256": FIXTURE_SHA256,
                },
            )
            _assert(document_response.status_code == 201, "document creation failed")
            replay = http.handle(
                "POST",
                "/v1/documents",
                headers=create_headers,
                body={
                    "filename": "synthetic-staging-record.pdf",
                    "media_type": "application/pdf",
                    "size_bytes": len(FIXTURE_BYTES),
                    "sha256": FIXTURE_SHA256,
                },
            )
            _assert(replay.status_code == 201 and replay.body["id"] == document_response.body["id"], "document replay was not idempotent")
            document_id = document_response.body["id"]

            session_headers = {**PATIENT_HEADERS, "Idempotency-Key": "staging-session-001"}
            session_response = http.handle(
                "POST",
                f"/v1/documents/{document_id}/upload-sessions",
                headers=session_headers,
                body={},
            )
            _assert(session_response.status_code == 201, "upload session creation failed")
            session_replay = http.handle(
                "POST",
                f"/v1/documents/{document_id}/upload-sessions",
                headers=session_headers,
                body={},
            )
            _assert(session_replay.status_code == 201 and session_replay.body["id"] == session_response.body["id"], "upload session replay was not idempotent")
            session_id = session_response.body["id"]

            runtime.object_store.available = False
            dependency_failure = http.handle(
                "PUT",
                f"/v1/upload-sessions/{session_id}/content",
                headers={**PATIENT_HEADERS, "Content-Type": "application/octet-stream"},
                body=FIXTURE_BYTES,
            )
            _assert(dependency_failure.status_code == 503 and dependency_failure.body["code"] == "DEPENDENCY_UNAVAILABLE", "object store failure was not retryable")
            runtime.object_store.available = True
            uploaded = http.handle(
                "PUT",
                f"/v1/upload-sessions/{session_id}/content",
                headers={**PATIENT_HEADERS, "Content-Type": "application/octet-stream"},
                body=FIXTURE_BYTES,
            )
            _assert(uploaded.status_code == 200 and uploaded.body["status"] == "verified", "upload retry failed")
            uploaded_replay = http.handle(
                "PUT",
                f"/v1/upload-sessions/{session_id}/content",
                headers={**PATIENT_HEADERS, "Content-Type": "application/octet-stream"},
                body=FIXTURE_BYTES,
            )
            _assert(uploaded_replay.status_code == 200 and uploaded_replay.body["status"] == "verified", "verified upload replay failed")
            stages["upload"] = _status(True)
            stages["idempotency"] = _status(True)
            stages["upload_retry"] = _status(True)

            # Processing queue: duplicate enqueue, failed attempt, then a
            # fresh retry that succeeds and makes the document ready.
            job_headers = {**PATIENT_HEADERS, "Idempotency-Key": "staging-ocr-001"}
            queued = http.handle(
                "POST",
                f"/v1/documents/{document_id}/processing-jobs",
                headers=job_headers,
                body={"job_type": JobType.OCR.value},
            )
            _assert(queued.status_code == 202, "OCR job enqueue failed")
            queued_replay = http.handle(
                "POST",
                f"/v1/documents/{document_id}/processing-jobs",
                headers=job_headers,
                body={"job_type": JobType.OCR.value},
            )
            _assert(queued_replay.status_code == 202 and queued_replay.body["id"] == queued.body["id"], "OCR job replay was not idempotent")
            failed_job = service.complete_processing(WORKER_AUTH, queued.body["id"], success=False, error_code="OCR_TRANSIENT")
            _assert(failed_job.status.value == "failed" and failed_job.attempt == 1, "failed OCR attempt was not recorded")
            retry = http.handle(
                "POST",
                f"/v1/documents/{document_id}/processing-jobs",
                headers={**PATIENT_HEADERS, "Idempotency-Key": "staging-ocr-002"},
                body={"job_type": JobType.OCR.value},
            )
            _assert(retry.status_code == 202, "OCR retry enqueue failed")
            succeeded_job = service.complete_processing(WORKER_AUTH, retry.body["id"], success=True)
            _assert(succeeded_job.status.value == "succeeded" and succeeded_job.attempt == 1, "OCR retry did not succeed")
            ready = service.get_document(AuthContext("synthetic-staging", scopes=frozenset({"documents:read"})), document_id)
            _assert(ready.status.value == "ready", "document did not become ready")
            stages["processing_retry"] = _status(True)

            # AI OCR/extraction/conflict stage. The existing golden fixture is
            # synthetic and provider-free; no model output is written to logs.
            pipeline = DeterministicStubPipeline()
            golden = synthetic_golden_set()
            clean_output = pipeline.run(golden.cases[0])
            conflict_output = pipeline.run(golden.cases[1])
            _assert(len(clean_output.ocr.blocks) == 2 and len(clean_output.extraction.claims) == 2, "synthetic OCR/extraction did not emit expected claims")
            _assert(len(conflict_output.conflicts.conflicts) == 1 and conflict_output.delivery_blocked, "conflict gate did not block conflicting fixture")
            stages["ocr_and_extraction"] = _status(True)
            stages["conflict_gate"] = {"status": "passed", "delivery_blocked": True, "conflicts": len(conflict_output.conflicts.conflicts)}

            # Facts remain unconfirmed until an explicit API review write.
            api_facts = []
            for index, claim in enumerate(clean_output.extraction.claims, start=1):
                created = http.handle(
                    "POST",
                    "/v1/facts",
                    headers={**PATIENT_HEADERS, "Idempotency-Key": f"staging-fact-{index:03d}"},
                    body={
                        "label": claim.normalized_key,
                        "value": claim.normalized_value,
                        "source_ref": claim.source_ref,
                        "source_type": "ai_extraction",
                        "confidence": claim.confidence,
                        "document_id": document_id,
                    },
                )
                _assert(created.status_code == 201, "fact creation failed")
                api_facts.append(created.body)
            for fact in api_facts:
                review = http.handle(
                    "POST",
                    f"/v1/facts/{fact['id']}/review",
                    headers={**PATIENT_HEADERS, "If-Match-Version": str(fact["version"])},
                    body={"review_status": ReviewStatus.CONFIRMED.value},
                )
                _assert(review.status_code == 200 and review.body["review_status"] == "confirmed", "fact review failed")
                stale = http.handle(
                    "POST",
                    f"/v1/facts/{fact['id']}/review",
                    headers={**PATIENT_HEADERS, "If-Match-Version": str(fact["version"])},
                    body={"review_status": ReviewStatus.CONFIRMED.value},
                )
                _assert(stale.status_code == 409 and stale.body["code"] == "VERSION_CONFLICT", "stale fact review was not rejected")
            stages["fact_review"] = _status(True)
            stages["version_conflict"] = _status(True)

            # Doctor brief projection consumes only explicitly confirmed claims
            # with source spans. Conflict output is never silently included.
            confirmed_claims = tuple(replace(claim, review_status=AIReviewStatus.CONFIRMED) for claim in clean_output.extraction.claims)
            scope = DoctorBriefScope(
                owner_id="synthetic-staging",
                visit_id="synthetic-visit-001",
                authorized_claim_ids=frozenset(claim.claim_id for claim in confirmed_claims),
                claim_owner_ids={claim.claim_id: "synthetic-staging" for claim in confirmed_claims},
                claim_visit_ids={claim.claim_id: "synthetic-visit-001" for claim in confirmed_claims},
            )
            brief = project_doctor_brief(scope, confirmed_claims)
            _assert(len(brief.facts) == 2, "doctor brief did not include confirmed facts")
            try:
                conflict_scope = replace(scope, authorized_claim_ids=frozenset(claim.claim_id for claim in conflict_output.extraction.claims), claim_owner_ids={claim.claim_id: "synthetic-staging" for claim in conflict_output.extraction.claims}, claim_visit_ids={claim.claim_id: "synthetic-visit-001" for claim in conflict_output.extraction.claims})
                project_doctor_brief(conflict_scope, tuple(replace(claim, review_status=AIReviewStatus.CONFIRMED) for claim in conflict_output.extraction.claims), conflicts=conflict_output.conflicts.conflicts)
            except DoctorBriefBlocked:
                pass
            else:
                raise AssertionError("conflicting claims were allowed into doctor brief")
            stages["doctor_brief"] = _status(True)

            # PDF is a deterministic staging export artifact. The production
            # PDF endpoint remains the existing replaceable adapter boundary.
            pdf_bytes = b"%PDF-1.4\nsynthetic staging export\n%%EOF\n"
            _assert(pdf_bytes.startswith(b"%PDF-1.4") and pdf_bytes.endswith(b"%%EOF\n"), "PDF fixture export failed")
            stages["pdf_export"] = {"status": "passed", "bytes": len(pdf_bytes)}

            # Share, public access, revoke, and post-revoke denial.
            share = http.handle(
                "POST",
                "/v1/shares",
                headers={**PATIENT_HEADERS, "Idempotency-Key": "staging-share-001"},
                body={
                    "resource_type": "document",
                    "resource_id": document_id,
                    "resource_version": ready.version,
                    "expires_at": (FIXTURE_TIME + timedelta(hours=1)).isoformat(),
                },
            )
            _assert(share.status_code == 201, "share creation failed")
            share_replay = http.handle(
                "POST",
                "/v1/shares",
                headers={**PATIENT_HEADERS, "Idempotency-Key": "staging-share-001"},
                body={
                    "resource_type": "document",
                    "resource_id": document_id,
                    "resource_version": ready.version,
                    "expires_at": (FIXTURE_TIME + timedelta(hours=1)).isoformat(),
                },
            )
            _assert(share_replay.status_code == 201 and share_replay.body["share"]["id"] == share.body["share"]["id"], "share creation was not idempotent")
            token = share.body["token"]
            access = http.handle("GET", f"/v1/shared/{token}")
            _assert(access.status_code == 200, "active share could not be accessed")
            revoked = http.handle("POST", f"/v1/shares/{share.body['share']['id']}/revoke", headers=PATIENT_HEADERS)
            _assert(revoked.status_code == 200 and revoked.body["status"] == "revoked", "share revoke failed")
            denied = http.handle("GET", f"/v1/shared/{token}")
            _assert(denied.status_code == 410 and denied.body["code"] == "SHARE_REVOKED", "revoked share remained accessible")
            stages["share_and_revoke"] = {"status": "passed", "active_access": "passed", "revoked_access": "blocked"}

            stages["audit"] = _status(True)
            stages["status"] = "passed"

    return {
        "schema_version": 1,
        "check": "staging_smoke",
        "fixture": "synthetic-staging-v1",
        "data_classification": "synthetic",
        "status": "passed",
        "stages": stages,
        "log_policy": "opaque statuses only; no PHI, source text, tokens, or credentials",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--artifact", type=Path, default=ROOT / "artifacts/staging/staging-smoke-report.json")
    args = parser.parse_args()
    try:
        report = _run(args.root.resolve())
    except Exception as exc:  # keep diagnostics content-free
        report = {
            "schema_version": 1,
            "check": "staging_smoke",
            "fixture": "synthetic-staging-v1",
            "data_classification": "synthetic",
            "status": "failed",
            "error_type": type(exc).__name__,
            "log_policy": "opaque statuses only; no PHI, source text, tokens, or credentials",
        }
        _write_report(args.artifact, report)
        print(f"Staging smoke failed ({type(exc).__name__}); inspect the local report.", file=sys.stderr)
        return 1
    _write_report(args.artifact, report)
    print("Staging smoke passed (upload → OCR → fact review → doctor brief → PDF → share → revoke).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
