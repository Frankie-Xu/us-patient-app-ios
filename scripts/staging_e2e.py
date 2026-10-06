#!/usr/bin/env python3
"""Deterministic staging acceptance flow for the patient product loop.

The harness uses only synthetic identifiers and the provider-neutral API/AI
boundaries. It is intentionally offline so staging smoke failures are
reproducible in CI without model-provider credentials or patient data.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ai import (
    Claim,
    DeterministicStubPipeline,
    DoctorBriefBlocked,
    DoctorBriefScope,
    DoctorBriefTask,
    GoldenCase,
    ReviewStatus,
    SourceSpan,
    project_doctor_brief,
)
from services.api.app import ApiHttpAdapter
from services.api.models import AuthContext, JobType, PrincipalRole, Scope
from services.api.service import ApiService


SCOPES = ",".join(
    scope.value
    for scope in (
        Scope.DOCUMENTS_READ,
        Scope.DOCUMENTS_WRITE,
        Scope.FACTS_READ,
        Scope.FACTS_WRITE,
        Scope.VISITS_READ,
        Scope.VISITS_WRITE,
        Scope.TASKS_WRITE,
        Scope.SHARES_CREATE,
        Scope.SHARES_REVOKE,
        Scope.AUDIT_READ,
    )
)
OWNER_ID = "patient-staging"
SYNTHETIC_CONTENT = b"synthetic staging patient note v1"
CONTENT_SHA256 = hashlib.sha256(SYNTHETIC_CONTENT).hexdigest()


def bearer(*, request_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OWNER_ID}|{SCOPES}|patient",
        "X-Request-Id": request_id,
    }


def assert_status(response: object, expected: int, label: str) -> dict:
    status = getattr(response, "status_code")
    body = getattr(response, "body")
    if status != expected:
        raise AssertionError(f"{label}: expected {expected}, got {status}: {body!r}")
    if not isinstance(body, dict):
        raise AssertionError(f"{label}: expected an object response")
    return body


def create_uploaded_document(http: ApiHttpAdapter, suffix: str) -> str:
    headers = {**bearer(request_id=f"{suffix}-document"), "Idempotency-Key": f"{suffix}-document"}
    created = assert_status(
        http.handle(
            "POST",
            "/v1/documents",
            headers=headers,
            body={
                "filename": f"{suffix}.pdf",
                "media_type": "application/pdf",
                "size_bytes": len(SYNTHETIC_CONTENT),
                "sha256": CONTENT_SHA256,
            },
        ),
        201,
        f"{suffix} document",
    )
    document_id = created["id"]
    session = assert_status(
        http.handle(
            "POST",
            f"/v1/documents/{document_id}/upload-sessions",
            headers={**bearer(request_id=f"{suffix}-session"), "Idempotency-Key": f"{suffix}-session"},
            body={},
        ),
        201,
        f"{suffix} upload session",
    )
    assert_status(
        http.handle(
            "PUT",
            f"/v1/upload-sessions/{session['id']}/content",
            headers={**bearer(request_id=f"{suffix}-content"), "Content-Type": "application/octet-stream"},
            body=SYNTHETIC_CONTENT,
        ),
        200,
        f"{suffix} content",
    )
    return document_id


def run() -> dict[str, object]:
    now = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
    service = ApiService(clock=lambda: now[0])
    http = ApiHttpAdapter(service)
    worker = AuthContext(
        "staging-worker",
        roles=frozenset({PrincipalRole.SERVICE}),
        scopes=frozenset(),
        request_id="staging-worker-request",
    )

    document_id = create_uploaded_document(http, "staging")
    queued = assert_status(
        http.handle(
            "POST",
            f"/v1/documents/{document_id}/processing-jobs",
            headers={**bearer(request_id="staging-ocr"), "Idempotency-Key": "staging-ocr"},
            body={"job_type": JobType.OCR.value},
        ),
        202,
        "OCR queue",
    )
    completed = service.complete_processing(worker, queued["id"], success=True)
    if completed.status.value != "succeeded":
        raise AssertionError("OCR job did not complete successfully")

    case_claim = Claim(
        claim_id="staging-claim-1",
        text_en="Follow-up visit scheduled",
        text_zh="已安排复诊",
        source_ref="staging-document:page-1",
        source_type="uploaded_document",
        source_span=SourceSpan(start=0, end=26, page=1),
        confidence=0.91,
        review_status=ReviewStatus.UNREVIEWED,
        normalized_key="visit_reason",
        normalized_value="follow-up",
    )
    case = GoldenCase(
        case_id="staging-case-1",
        document_source_ref="staging-document",
        document_source_type="uploaded_document",
        document_text=(
            "FACT\t"
            + json.dumps(
                {
                    **case_claim.to_dict(),
                    "source_span": {"start": 0, "end": 26, "page": 1},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
        expected_claims=(case_claim,),
        data_classification="synthetic",
    )
    pipeline = DeterministicStubPipeline()
    output = pipeline.run(case)
    if len(output.extraction.claims) != 1:
        raise AssertionError("AI extraction did not produce the synthetic claim")
    if output.conflicts.conflicts:
        raise AssertionError("unexpected conflict in the synthetic claim")
    if output.citations.coverage != 1.0:
        raise AssertionError("synthetic claim lost its source span mapping")
    extracted = output.extraction.claims[0]

    fact = assert_status(
        http.handle(
            "POST",
            "/v1/facts",
            headers={**bearer(request_id="staging-fact"), "Idempotency-Key": "staging-fact"},
            body={
                "label": "visit_reason",
                "value": extracted.text_en,
                "source_ref": extracted.source_ref,
                "source_type": "ai_extraction",
                "confidence": extracted.confidence,
                "document_id": document_id,
            },
        ),
        201,
        "fact extraction projection",
    )
    reviewed = assert_status(
        http.handle(
            "POST",
            f"/v1/facts/{fact['id']}/review",
            headers={**bearer(request_id="staging-review"), "If-Match-Version": "1"},
            body={"review_status": ReviewStatus.CONFIRMED.value},
        ),
        200,
        "fact review",
    )
    if reviewed["review_status"] != ReviewStatus.CONFIRMED.value:
        raise AssertionError("fact review did not confirm the synthetic fact")

    topic = assert_status(
        http.handle(
            "POST",
            "/v1/topics",
            headers={**bearer(request_id="staging-topic"), "Idempotency-Key": "staging-topic"},
            body={"name": "Synthetic follow-up"},
        ),
        201,
        "visit topic",
    )
    visit = assert_status(
        http.handle(
            "POST",
            "/v1/visits",
            headers={**bearer(request_id="staging-visit"), "Idempotency-Key": "staging-visit"},
            body={
                "title": "Synthetic follow-up",
                "starts_at": "2030-01-01T09:00:00+00:00",
                "topic_ids": [topic["id"]],
            },
        ),
        201,
        "visit",
    )

    confirmed_claim = replace(extracted, review_status=ReviewStatus.CONFIRMED)
    question_claim = Claim(
        claim_id="staging-question-1",
        text_en="Ask about the next follow-up date",
        text_zh="询问下一次复诊日期",
        source_ref="staging:user-input:question",
        source_type="user_input",
        source_span=SourceSpan(start=0, end=32, page=1),
        confidence=1.0,
        review_status=ReviewStatus.CONFIRMED,
    )
    scope = DoctorBriefScope(
        owner_id=OWNER_ID,
        visit_id=visit["id"],
        authorized_claim_ids=frozenset({confirmed_claim.claim_id, question_claim.claim_id}),
        claim_owner_ids={
            confirmed_claim.claim_id: OWNER_ID,
            question_claim.claim_id: OWNER_ID,
        },
        claim_visit_ids={
            confirmed_claim.claim_id: visit["id"],
            question_claim.claim_id: visit["id"],
        },
    )
    brief = project_doctor_brief(
        scope,
        facts=(confirmed_claim,),
        tasks=(
            DoctorBriefTask(
                task_id="staging-task-1",
                owner_id=OWNER_ID,
                visit_id=visit["id"],
                content=question_claim,
            ),
        ),
    )
    brief_payload = brief.to_dict()
    if not brief_payload["facts"] or not brief_payload["user_tasks"]:
        raise AssertionError("doctor brief did not include facts and questions")

    try:
        project_doctor_brief(scope, facts=(extracted,))
    except DoctorBriefBlocked as blocked:
        if not blocked.codes:
            raise AssertionError("blocked doctor brief did not report a reason")
    else:
        raise AssertionError("unreviewed claim unexpectedly passed the doctor-view gate")

    ready_document = service.get_document(
        AuthContext(
            OWNER_ID,
            roles=frozenset({PrincipalRole.PATIENT}),
            scopes=frozenset({Scope.DOCUMENTS_READ}),
            request_id="staging-version",
        ),
        document_id,
    )
    shared = assert_status(
        http.handle(
            "POST",
            "/v1/shares",
            headers={**bearer(request_id="staging-share"), "Idempotency-Key": "staging-share"},
            body={
                "resource_type": "document",
                "resource_id": document_id,
                "resource_version": ready_document.version,
                "expires_at": (now[0] + timedelta(hours=1)).isoformat(),
            },
        ),
        201,
        "share",
    )
    assert_status(http.handle("GET", f"/v1/shared/{shared['token']}"), 200, "share access")
    assert_status(
        http.handle(
            "POST",
            f"/v1/shares/{shared['share']['id']}/revoke",
            headers=bearer(request_id="staging-revoke"),
        ),
        200,
        "share revoke",
    )
    revoked = http.handle("GET", f"/v1/shared/{shared['token']}")
    if revoked.status_code != 410 or revoked.body.get("code") != "SHARE_REVOKED":
        raise AssertionError(f"revoked share remained accessible: {revoked.body!r}")

    retry_document_id = create_uploaded_document(http, "staging-retry")
    failed_job = assert_status(
        http.handle(
            "POST",
            f"/v1/documents/{retry_document_id}/processing-jobs",
            headers={**bearer(request_id="staging-fail"), "Idempotency-Key": "staging-fail"},
            body={"job_type": JobType.OCR.value},
        ),
        202,
        "failure queue",
    )
    failed = service.complete_processing(worker, failed_job["id"], success=False, error_code="SYNTHETIC_RETRYABLE")
    if failed.status.value != "failed" or failed.error_code != "SYNTHETIC_RETRYABLE":
        raise AssertionError("failed processing did not retain retryable state")
    retried_job = assert_status(
        http.handle(
            "POST",
            f"/v1/documents/{retry_document_id}/processing-jobs",
            headers={**bearer(request_id="staging-retry"), "Idempotency-Key": "staging-retry"},
            body={"job_type": JobType.OCR.value},
        ),
        202,
        "retry queue",
    )
    retried = service.complete_processing(worker, retried_job["id"], success=True)
    if retried.status.value != "succeeded":
        raise AssertionError("retry did not recover the failed job")

    return {
        "flow": [
            "upload",
            "ocr",
            "extract",
            "review",
            "doctor_brief",
            "share",
            "revoke",
        ],
        "document_version": ready_document.version,
        "fact_id": fact["id"],
        "visit_id": visit["id"],
        "brief_schema": brief_payload["brief_schema"],
        "brief_fact_count": len(brief_payload["facts"]),
        "brief_task_count": len(brief_payload["user_tasks"]),
        "retry_status": retried.status.value,
        "synthetic": True,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
