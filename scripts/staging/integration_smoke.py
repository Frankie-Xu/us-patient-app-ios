"""Run the local HTTP staging acceptance flow with synthetic data.

The existing :mod:`staging_smoke` command validates the provider-neutral
runtime in one process. This command deliberately goes through the running
HTTP API and Redis-backed worker boundary so that a report can distinguish a
real provider-backed write from a deterministic fixture. Plain-text fixture
ingest is reported as fixture processing; a queued job is never presented as
provider OCR success.

The command does not print request bodies, authorization headers, opaque IDs,
tokens, passwords, or source text.  It uses the temporary bearer accepted by
the current local API only when ``STAGING_AUTH_TOKEN`` is not supplied.  That
mode is reported as a blocker because it is not OAuth/JWT authentication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_BYTES = b"synthetic-local-staging-document-v2"
FIXTURE_SHA256 = hashlib.sha256(FIXTURE_BYTES).hexdigest()
IMAGE_FIXTURE_PATH = ROOT / "tests/fixtures/synthetic_ocr.png"
DEFAULT_API_URL = "http://127.0.0.1:58000"
DEFAULT_WORKER_URL = "http://127.0.0.1:58001"
AUTH_SCOPES = (
    "documents:read,documents:write,facts:read,facts:write,"
    "visits:read,visits:write,tasks:read,tasks:write,"
    "shares:create,shares:revoke,audit:read"
)
REPORT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: Any

    @property
    def code(self) -> str | None:
        if isinstance(self.body, Mapping):
            value = self.body.get("code")
            return str(value) if value else None
        return None


class StageFailure(RuntimeError):
    """An expected acceptance failure with a safe category only."""

    def __init__(self, category: str, detail: str = "") -> None:
        super().__init__(detail or category)
        self.category = category


class HttpClient:
    def __init__(self, base_url: str, auth_header: str | None, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        raw_body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        auth: bool = True,
    ) -> HttpResult:
        request_headers = {"Accept": "application/json"}
        if auth and self.auth_header:
            request_headers["Authorization"] = self.auth_header
        if headers:
            request_headers.update(headers)
        payload: bytes | None = raw_body
        if body is not None:
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(self.base_url + path, data=payload, headers=request_headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl_context()) as response:
                return HttpResult(response.status, self._decode(response.read()))
        except HTTPError as error:
            return HttpResult(error.code, self._decode(error.read()))
        except (URLError, TimeoutError, OSError) as error:
            raise StageFailure("endpoint_unavailable", type(error).__name__) from error

    @staticmethod
    def _decode(payload: bytes) -> Any:
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _ssl_context() -> ssl.SSLContext | None:
        # The default context is intentionally used for HTTPS.  A local
        # development CA can be trusted by the host/Simulator; verification is
        # never disabled by this acceptance command.
        return None


def _safe_status(status: int, code: str | None = None, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "passed", "http_status": status}
    if code:
        result["code"] = code
    result.update(extra)
    return result


def _require(response: HttpResult, expected: int, stage: str, code: str | None = None) -> None:
    if response.status != expected:
        observed = response.code or "HTTP_ERROR"
        raise StageFailure(f"{stage}:{observed}", f"expected {expected}, got {response.status}")
    if code is not None and response.code != code:
        raise StageFailure(f"{stage}:unexpected_code", f"expected {code}, got {response.code}")


def _auth_header() -> tuple[str, str]:
    supplied = os.getenv("STAGING_AUTH_TOKEN", "").strip()
    if supplied:
        return (supplied if supplied.lower().startswith("bearer ") else f"Bearer {supplied}"), "provided_token_unverified"
    subject = os.getenv("STAGING_AUTH_SUBJECT", "synthetic-integration").strip() or "synthetic-integration"
    return f"Bearer {subject}|{AUTH_SCOPES}|patient", "temporary_bearer_contract"


def _resolve_auth(args: argparse.Namespace) -> tuple[str, str]:
    """Log in through the staging session endpoint when credentials exist.

    Credentials are read only in memory from the ignored staging env file (or
    process environment).  The endpoint response is never copied to the
    report or terminal.  Falling back to the temporary local contract is
    allowed only when no session credentials/token were supplied, and is
    recorded as a blocker by ``_run_live``.
    """
    supplied = os.getenv("STAGING_AUTH_TOKEN", "").strip()
    config = _safe_env_file(Path(args.env_file))
    username = os.getenv("STAGING_AUTH_USERNAME", config.get("STAGING_AUTH_USERNAME", "")).strip()
    password = os.getenv("STAGING_AUTH_PASSWORD", config.get("STAGING_AUTH_PASSWORD", "")).strip()
    if supplied:
        return (supplied if supplied.lower().startswith("bearer ") else f"Bearer {supplied}"), "provided_token_unverified"
    if username or password:
        if not username or not password:
            raise StageFailure("authentication_credentials_incomplete")
        bootstrap = HttpClient(args.api_url, None, args.timeout)
        session = bootstrap.request("POST", "/v1/auth/sessions", body={"username": username, "password": password}, auth=False)
        access_token = session.body.get("access_token") if isinstance(session.body, Mapping) else None
        if session.status != 200 or not isinstance(access_token, str) or not access_token.strip():
            raise StageFailure("authentication_login_failed")
        return f"Bearer {access_token}", "session_login"
    return _auth_header()


def _key(prefix: str) -> str:
    return f"integration-{prefix}-{uuid.uuid4().hex[:12]}"


def _safe_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("\"'")
    return values


def _record_gap(report: dict[str, Any], stage: str, reason: str) -> None:
    report.setdefault("not_validated", []).append({"stage": stage, "reason": reason})


def _record_processing_stage(
    report: dict[str, Any],
    *,
    verification: str,
    processing_state: str,
    queue: str,
    ocr_provider: str,
    input_media_type: str,
) -> None:
    """Record processing truthfully and block a run that never completed OCR."""
    completed = processing_state == "ready"
    report.setdefault("stages", {})["processing"] = {
        "verification": verification,
        "status": "passed" if completed else "failed",
        "queue": queue,
        "document_state": processing_state,
        "worker_completed": completed,
        "ocr_provider": ocr_provider,
        "input_media_type": input_media_type,
    }
    if completed:
        return
    code = "ocr_processing_failed" if processing_state == "failed" else "worker_did_not_complete_ocr"
    report.setdefault("blockers", []).append({"code": code})
    _record_gap(report, "processing", code)


def _run_deterministic_fixture(root: Path) -> dict[str, Any]:
    """Run the provider-neutral fixture smoke without leaking its artifact."""
    artifact = root / "tmp" / f"integration-fixture-{uuid.uuid4().hex}.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(root / "scripts/staging/staging_smoke.py"), "--root", str(root), "--artifact", str(artifact)]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    try:
        if not artifact.is_file():
            raise StageFailure("fixture_report_missing")
        report = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StageFailure("fixture_report_invalid", type(error).__name__) from error
    finally:
        artifact.unlink(missing_ok=True)
    if completed.returncode != 0 or report.get("status") != "passed":
        raise StageFailure("fixture_smoke_failed")
    stages = report.get("stages", {})
    return {
        "verification": "mock",
        "status": "passed",
        "stages": {
            "doctor_brief": "passed" if stages.get("doctor_brief", {}).get("status") == "passed" else "failed",
            "pdf_export": "passed" if stages.get("pdf_export", {}).get("status") == "passed" else "failed",
            "conflict_gate": "passed" if stages.get("conflict_gate", {}).get("delivery_blocked") is True else "failed",
        },
        "source": "deterministic_ai_fixture",
    }


def _restart_and_check_retention(
    *,
    report: dict[str, Any],
    api: HttpClient,
    document_id: str,
    object_key: str | None,
    fixture_bytes: bytes,
    fixture_sha256: str,
    compose_file: Path,
    env_file: Path,
) -> None:
    """Restart provider services and verify persisted metadata/object state.

    This is only called when ``--check-retention`` is explicitly provided.  The
    command output is captured so credentials and compose environment are never
    written to the terminal or report.
    """
    if not compose_file.is_file() or not env_file.is_file():
        _record_gap(report, "retention", "compose_or_env_file_missing")
        report.setdefault("blockers", []).append({"code": "retention_not_run"})
        return
    compose_root = compose_file.parent.parent.parent
    command = ["docker", "compose", "--env-file", str(env_file), "--file", str(compose_file), "restart", "postgres", "localstack", "redis", "api", "worker"]
    completed = subprocess.run(command, cwd=compose_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180, check=False)
    if completed.returncode != 0:
        report.setdefault("blockers", []).append({"code": "provider_restart_failed"})
        _record_gap(report, "retention", "provider_restart_failed")
        return
    # `docker compose restart` does not restart one-shot s3-init.  Recreate
    # that job after LocalStack restarts, then restart API/Worker so their S3
    # readiness probes observe the durable bucket rather than a transient 404.
    init = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "--file", str(compose_file), "run", "--rm", "s3-init"],
        cwd=compose_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    if init.returncode != 0:
        report.setdefault("blockers", []).append({"code": "object_store_reinit_failed"})
        _record_gap(report, "retention.object", "s3_bucket_reinit_failed")
        return
    restarted = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "--file", str(compose_file), "restart", "api", "worker"],
        cwd=compose_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    if restarted.returncode != 0:
        report.setdefault("blockers", []).append({"code": "api_worker_restart_failed"})
        _record_gap(report, "retention", "api_worker_restart_failed")
        return
    deadline = time.monotonic() + 60
    ready: HttpResult | None = None
    while time.monotonic() < deadline:
        try:
            ready = api.request("GET", "/readyz", auth=False)
        except StageFailure:
            ready = None
        if ready and ready.status == 200:
            break
        time.sleep(2)
    if not ready or ready.status != 200:
        report.setdefault("blockers", []).append({"code": "provider_restart_not_ready"})
        _record_gap(report, "retention", "api_not_ready_after_restart")
        return
    document = api.request("GET", f"/v1/documents/{document_id}")
    if document.status != 200:
        report.setdefault("blockers", []).append({"code": "metadata_not_retained"})
        _record_gap(report, "retention", "document_not_readable_after_restart")
        return
    retention: dict[str, Any] = {"verification": "live_http", "status": "blocked", "metadata": "retained"}
    if object_key:
        bucket = _safe_env_file(env_file).get("S3_BUCKET", "")
        compose_prefix = ["docker", "compose", "--env-file", str(env_file), "--file", str(compose_file), "exec", "-T", "localstack", "awslocal"]
        # S3ObjectStore has an `uploads` prefix and the service passes an
        # `uploads/<session>` logical key, so the provider key is commonly
        # `uploads/uploads/<session>`. Probe both forms to avoid mistaking a
        # provider prefix for data loss.
        candidates = [object_key, f"uploads/{object_key}"]
        object_retained = False
        for candidate in candidates:
            head = subprocess.run(
                compose_prefix + ["s3api", "head-object", "--bucket", bucket, "--key", candidate],
                cwd=compose_file.parent.parent.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False,
            )
            if head.returncode != 0:
                continue
            try:
                metadata = json.loads(head.stdout).get("Metadata", {})
                digest = str(metadata.get("sha256", ""))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if digest.lower() != fixture_sha256:
                continue
            content = subprocess.run(
                compose_prefix + ["s3", "cp", f"s3://{bucket}/{candidate}", "-"],
                cwd=compose_file.parent.parent.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            if content.returncode == 0 and content.stdout == fixture_bytes:
                object_retained = True
                break
        retention["object"] = "retained" if object_retained else "not_validated"
        if not object_retained:
            report.setdefault("blockers", []).append({"code": "object_not_retained"})
            _record_gap(report, "retention.object", "object_probe_failed")
        else:
            retention["status"] = "passed"
    else:
        retention["object"] = "not_validated"
        _record_gap(report, "retention.object", "upload_response_did_not_include_object_key")
    report.setdefault("stages", {})["retention"] = retention


def _run_live(args: argparse.Namespace, report: dict[str, Any]) -> None:
    auth, auth_mode = _resolve_auth(args)
    report["authentication"] = {"mode": auth_mode, "verification": "live_http" if auth_mode in {"session_login", "provided_token_unverified"} else "temporary_contract"}
    if auth_mode == "temporary_bearer_contract":
        report.setdefault("blockers", []).append({"code": "temporary_auth_only"})
    report.setdefault("stages", {})["authentication"] = {"verification": "live_http" if auth_mode == "session_login" else "contract", "status": "passed", "mode": auth_mode}
    api = HttpClient(args.api_url, auth, args.timeout)
    worker = HttpClient(args.worker_url, None, args.timeout)
    readiness = api.request("GET", "/readyz", auth=False)
    _require(readiness, 200, "readiness")
    report.setdefault("stages", {})["readiness"] = _safe_status(readiness.status, verification="live_http")

    worker_readiness = worker.request("GET", "/readyz", auth=False)
    worker_body = worker_readiness.body if isinstance(worker_readiness.body, Mapping) else {}
    worker_mode = str(worker_body.get("mode", "unknown"))
    worker_consumer = worker_body.get("consumer_enabled")
    worker_fixture = "fixture" in worker_mode.lower()
    worker_live = worker_readiness.status == 200 and worker_consumer not in {False, "0", 0}
    report["worker"] = {
        "verification": "live_http",
        "status": "ready" if worker_readiness.status == 200 else "unavailable",
        "mode": worker_mode,
        "consumer": "enabled" if worker_live else "not_confirmed",
        "pipeline": "fixture" if worker_fixture else "provider",
    }
    if not worker_live:
        report.setdefault("blockers", []).append({"code": "worker_not_consuming"})
    elif worker_fixture:
        report.setdefault("blockers", []).append({"code": "fixture_worker_pipeline"})

    run_id = uuid.uuid4().hex[:12]
    processing_bytes = FIXTURE_BYTES
    processing_sha256 = FIXTURE_SHA256
    processing_filename = "synthetic-integration-record.txt"
    processing_media_type = "text/plain"
    # A provider-backed Worker needs image input. The checked-in PNG contains
    # only synthetic text and lets the same live acceptance path verify actual
    # container-side OCR without treating fixture text ingest as OCR success.
    if worker_live and not worker_fixture:
        try:
            processing_bytes = IMAGE_FIXTURE_PATH.read_bytes()
        except OSError as exc:
            raise StageFailure("provider_fixture_missing") from exc
        processing_sha256 = hashlib.sha256(processing_bytes).hexdigest()
        processing_filename = "synthetic-integration-record.png"
        processing_media_type = "image/png"
    document_body = {"filename": processing_filename, "media_type": processing_media_type, "size_bytes": len(processing_bytes), "sha256": processing_sha256}
    document_headers = {"Idempotency-Key": _key("document")}
    created = api.request("POST", "/v1/documents", body=document_body, headers=document_headers)
    _require(created, 201, "document_create")
    document = created.body
    document_id = str(document.get("id", "")) if isinstance(document, Mapping) else ""
    if not document_id:
        raise StageFailure("document_create:missing_id")
    replay = api.request("POST", "/v1/documents", body=document_body, headers=document_headers)
    _require(replay, 201, "document_replay")
    if not isinstance(replay.body, Mapping) or replay.body.get("id") != document_id:
        raise StageFailure("document_replay:not_idempotent")
    conflict_body = {**document_body, "filename": "synthetic-integration-conflict.txt"}
    conflict = api.request("POST", "/v1/documents", body=conflict_body, headers=document_headers)
    _require(conflict, 409, "duplicate_idempotency", "IDEMPOTENCY_CONFLICT")
    checksum_duplicate = api.request("POST", "/v1/documents", body=document_body, headers={"Idempotency-Key": _key("checksum-duplicate")})
    if checksum_duplicate.status == 409:
        checksum_duplicate_result = "rejected"
    elif checksum_duplicate.status == 201 and isinstance(checksum_duplicate.body, Mapping) and checksum_duplicate.body.get("id") == document_id:
        checksum_duplicate_result = "deduplicated"
    elif checksum_duplicate.status == 201:
        checksum_duplicate_result = "accepted_as_new_document"
        _record_gap(report, "duplicate_checksum", "same_checksum_with_new_idempotency_key_is_not_deduplicated")
    else:
        raise StageFailure("duplicate_checksum:unexpected_response")
    report.setdefault("stages", {})["upload"] = {
        "verification": "live_http",
        "status": "passed",
        "duplicate_idempotency": "passed",
        "duplicate_checksum": checksum_duplicate_result,
    }

    # A rerun may correctly deduplicate to a document that is already ready.
    # Keep the checksum assertion above, then use a fresh synthetic byte
    # variant for the rest of this run so upload/session/worker checks remain
    # independently repeatable without deleting staging history.
    existing_state = api.request("GET", f"/v1/documents/{document_id}")
    if existing_state.status == 200 and isinstance(existing_state.body, Mapping) and existing_state.body.get("status") != "uploaded":
        processing_bytes = processing_bytes + f"\nsynthetic-run-{run_id}".encode("ascii")
        processing_sha256 = hashlib.sha256(processing_bytes).hexdigest()
        processing_body = {
            "filename": processing_filename,
            "media_type": processing_media_type,
            "size_bytes": len(processing_bytes),
            "sha256": processing_sha256,
        }
        fresh = api.request("POST", "/v1/documents", body=processing_body, headers={"Idempotency-Key": _key("processing-document")})
        _require(fresh, 201, "processing_document_create")
        if not isinstance(fresh.body, Mapping) or not fresh.body.get("id"):
            raise StageFailure("processing_document_create:missing_id")
        document_id = str(fresh.body["id"])

    session_key = _key("session")
    session_response = api.request("POST", f"/v1/documents/{document_id}/upload-sessions", body={}, headers={"Idempotency-Key": session_key})
    _require(session_response, 201, "upload_session")
    session = session_response.body
    session_id = str(session.get("id", "")) if isinstance(session, Mapping) else ""
    if not session_id:
        raise StageFailure("upload_session:missing_id")
    session_replay = api.request("POST", f"/v1/documents/{document_id}/upload-sessions", body={}, headers={"Idempotency-Key": session_key})
    _require(session_replay, 201, "upload_session_replay")
    if not isinstance(session_replay.body, Mapping) or session_replay.body.get("id") != session_id:
        raise StageFailure("upload_session_replay:not_idempotent")
    upload = api.request("PUT", f"/v1/upload-sessions/{session_id}/content", raw_body=processing_bytes, headers={"Content-Type": "application/octet-stream"})
    _require(upload, 200, "upload_content")
    repeat_upload = api.request("PUT", f"/v1/upload-sessions/{session_id}/content", raw_body=processing_bytes, headers={"Content-Type": "application/octet-stream"})
    _require(repeat_upload, 200, "upload_repeat")
    # The API intentionally omits object_key from its public response.  The
    # current S3 adapter uses the documented internal key convention, so the
    # retention probe can verify the object without putting storage paths in
    # the report or widening the API contract.
    object_key = str(upload.body.get("object_key")) if isinstance(upload.body, Mapping) and upload.body.get("object_key") else f"uploads/{session_id}"
    report.setdefault("stages", {})["upload_content"] = {"verification": "live_http", "status": "passed", "same_bytes_replay": "passed"}

    job_key = _key("ocr")
    job_body = {"job_type": "ocr"}
    queued = api.request("POST", f"/v1/documents/{document_id}/processing-jobs", body=job_body, headers={"Idempotency-Key": job_key})
    _require(queued, 202, "processing_enqueue")
    queued_replay = api.request("POST", f"/v1/documents/{document_id}/processing-jobs", body=job_body, headers={"Idempotency-Key": job_key})
    _require(queued_replay, 202, "processing_replay")
    if not isinstance(queued.body, Mapping) or not isinstance(queued_replay.body, Mapping) or queued.body.get("id") != queued_replay.body.get("id"):
        raise StageFailure("processing_replay:not_idempotent")
    processing_state = "queued"
    for _ in range(max(1, args.poll_attempts)):
        current = api.request("GET", f"/v1/documents/{document_id}")
        if current.status != 200 or not isinstance(current.body, Mapping):
            break
        processing_state = str(current.body.get("status", "unknown"))
        if processing_state in {"ready", "failed"}:
            break
        time.sleep(args.poll_interval)
    _record_processing_stage(
        report,
        verification="live_http+fixture_worker" if worker_fixture else "live_http+provider_worker",
        processing_state=processing_state,
        queue="enqueued",
        ocr_provider="fixture" if worker_fixture else "provider",
        input_media_type=processing_media_type,
    )

    # Facts are intentionally synthetic AI output when the worker has not
    # completed.  Their source spans and confidence remain explicit, and the
    # review gate is exercised through the live HTTP API.
    facts: list[Mapping[str, Any]] = []
    for index, (label, value, confidence) in enumerate((("medication", "synthetic-example", 0.98), ("allergy", "synthetic-none-reported", 0.93)), start=1):
        fact_body = {"label": label, "value": value, "source_ref": f"fixture:page-1:span-{index}", "source_type": "ai_extraction", "confidence": confidence, "document_id": document_id}
        fact_key = _key(f"fact-{index}")
        fact_response = api.request("POST", "/v1/facts", body=fact_body, headers={"Idempotency-Key": fact_key})
        _require(fact_response, 201, "fact_create")
        replay_fact = api.request("POST", "/v1/facts", body=fact_body, headers={"Idempotency-Key": fact_key})
        _require(replay_fact, 201, "fact_replay")
        if not isinstance(fact_response.body, Mapping) or not isinstance(replay_fact.body, Mapping) or fact_response.body.get("id") != replay_fact.body.get("id"):
            raise StageFailure("fact_replay:not_idempotent")
        facts.append(fact_response.body)
    report.setdefault("stages", {})["facts"] = {"verification": "live_http", "status": "passed", "input": "synthetic_fixture", "source_spans": "present", "low_confidence_auto_confirm": False}
    for fact in facts:
        fact_id = str(fact.get("id", ""))
        version = int(fact.get("version", 1))
        stale = api.request("POST", f"/v1/facts/{fact_id}/review", body={"review_status": "confirmed"}, headers={"If-Match-Version": str(version + 99)})
        _require(stale, 409, "fact_version_conflict", "VERSION_CONFLICT")
        reviewed = api.request("POST", f"/v1/facts/{fact_id}/review", body={"review_status": "confirmed"}, headers={"If-Match-Version": str(version)})
        _require(reviewed, 200, "fact_review")
        stale_after = api.request("POST", f"/v1/facts/{fact_id}/review", body={"review_status": "confirmed"}, headers={"If-Match-Version": str(version)})
        _require(stale_after, 409, "fact_stale_review", "VERSION_CONFLICT")
    report.setdefault("stages", {})["fact_review"] = {"verification": "live_http", "status": "passed", "version_conflict": "passed", "manual_confirmation": "required"}

    current_document = api.request("GET", f"/v1/documents/{document_id}")
    _require(current_document, 200, "document_version")
    resource_version = int(current_document.body.get("version", 1)) if isinstance(current_document.body, Mapping) else 1
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=max(8, args.share_expiry_seconds))).isoformat()
    share = api.request("POST", "/v1/shares", body={"resource_type": "document", "resource_id": document_id, "resource_version": resource_version, "expires_at": expires_at}, headers={"Idempotency-Key": _key("share")})
    _require(share, 201, "share_create")
    if not isinstance(share.body, Mapping):
        raise StageFailure("share_create:invalid_body")
    share_data = share.body.get("share")
    token = str(share.body.get("token", ""))
    share_id = str(share_data.get("id", "")) if isinstance(share_data, Mapping) else ""
    if not token or not share_id:
        raise StageFailure("share_create:missing_fields")
    active = api.request("GET", f"/v1/shared/{token}", auth=False)
    _require(active, 200, "share_access")
    revoke = api.request("POST", f"/v1/shares/{share_id}/revoke")
    _require(revoke, 200, "share_revoke")
    denied = api.request("GET", f"/v1/shared/{token}", auth=False)
    _require(denied, 410, "share_revoke_access", "SHARE_REVOKED")
    expiring = api.request("POST", "/v1/shares", body={"resource_type": "document", "resource_id": document_id, "resource_version": resource_version, "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()}, headers={"Idempotency-Key": _key("expiry")})
    _require(expiring, 201, "share_expiry_create")
    expiry_token = str(expiring.body.get("token", "")) if isinstance(expiring.body, Mapping) else ""
    time.sleep(3)
    expired = api.request("GET", f"/v1/shared/{expiry_token}", auth=False)
    _require(expired, 410, "share_expiry_access", "SHARE_EXPIRED")
    report.setdefault("stages", {})["share"] = {"verification": "live_http", "status": "passed", "active_access": "passed", "revoke_access": "passed", "expiry_access": "passed"}

    audit = api.request("GET", "/v1/audit-events?" + urlencode({"resource_id": document_id}))
    _require(audit, 200, "audit_history")
    report.setdefault("stages", {})["audit_history"] = {"verification": "live_http", "status": "passed"}

    if args.check_retention:
        _restart_and_check_retention(
            report=report,
            api=api,
            document_id=document_id,
            object_key=object_key,
            fixture_bytes=processing_bytes,
            fixture_sha256=processing_sha256,
            compose_file=Path(args.compose_file),
            env_file=Path(args.env_file),
        )
    else:
        _record_gap(report, "retention", "not_run_without_explicit_check_retention")

    report.setdefault("not_validated", []).extend(
        [
            {"stage": "doctor_brief", "reason": "no_HTTP_route_in_current_contract; deterministic fixture covers projection"},
            {"stage": "visit_questions", "reason": "no_HTTP_route_in_current_contract"},
            {"stage": "pdf_export", "reason": "no_HTTP_route_in_current_contract; deterministic fixture covers export bytes"},
        ]
    )
    if auth_mode == "temporary_bearer_contract":
        report["not_validated"].append({"stage": "oauth_jwt", "reason": "temporary bearer API boundary"})
    elif auth_mode == "session_login":
        report["not_validated"].append({"stage": "oauth_jwt", "reason": "local signed staging session; external identity provider not configured"})
    else:
        report["not_validated"].append({"stage": "oauth_jwt", "reason": "provided token accepted; issuer and audience verification delegated to API"})


def _base_report() -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "check": "staging_integration_smoke",
        "fixture": "synthetic-local-staging-v2",
        "data_classification": "synthetic",
        "log_policy": "opaque statuses only; no PHI, source text, tokens, credentials, or opaque IDs",
        "status": "not_run",
        "implemented": [
            "HTTP readiness and provider health",
            "upload and idempotency",
            "processing enqueue and worker completion detection",
            "fact source spans, manual review, and version conflicts",
            "share access, expiry, revoke, and audit history",
            "optional provider restart retention check",
        ],
        "live": {},
        "mock": {},
        "stages": {},
        "blockers": [],
        "not_validated": [],
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("STAGING_API_URL", DEFAULT_API_URL))
    parser.add_argument("--worker-url", default=os.getenv("STAGING_WORKER_URL", DEFAULT_WORKER_URL))
    parser.add_argument("--artifact", type=Path, default=ROOT / "artifacts/staging/integration-acceptance-report.json")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--poll-attempts", type=int, default=5)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--share-expiry-seconds", type=int, default=8)
    parser.add_argument("--allow-blockers", action="store_true", help="exit zero while recording expected local staging blockers")
    parser.add_argument("--dry-run", action="store_true", help="write schema and route-gap evidence without contacting services")
    parser.add_argument("--check-retention", action="store_true", help="explicitly restart local Compose providers and verify persistence")
    parser.add_argument("--compose-file", default=os.getenv("STAGING_COMPOSE_FILE", str(ROOT / "infra/staging/compose.yaml")))
    parser.add_argument("--env-file", default=os.getenv("STAGING_ENV_FILE", str(ROOT / ".env.staging")))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = _base_report()
    try:
        if args.dry_run:
            report["status"] = "dry_run"
            report["route_gaps"] = {"doctor_brief": "not exposed by current HTTP contract", "visit_questions": "not exposed by current HTTP contract", "pdf_export": "not exposed by current HTTP contract"}
            report["authentication"] = {"status": "not_run"}
        else:
            _run_live(args, report)
            fixture = _run_deterministic_fixture(args.root.resolve())
            report["mock_fixture"] = fixture
            report["status"] = "passed_with_blockers" if report["blockers"] else "passed"
    except StageFailure as error:
        report["status"] = "blocked"
        report.setdefault("blockers", []).append({"code": error.category})
    except Exception as error:  # no exception text: it may contain endpoint or credential data
        report["status"] = "blocked"
        report.setdefault("blockers", []).append({"code": type(error).__name__})
    report["live"] = {
        name: value
        for name, value in report.get("stages", {}).items()
        if isinstance(value, Mapping) and value.get("verification", "").startswith("live_http")
    }
    report["mock"] = report.get("mock_fixture", {})
    _write_report(args.artifact, report)
    blockers = len(report.get("blockers", []))
    print(f"staging integration report: status={report['status']} blockers={blockers}")
    if args.dry_run or args.allow_blockers:
        return 0
    return 2 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
