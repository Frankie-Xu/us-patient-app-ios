"""Local staging worker with durable Redis delivery and bounded retries."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from services.api.models import DocumentStatus, JobStatus, UploadProcessingJob
from services.api.provider_adapters import PostgresMetadataStore, ProviderSettings, RedisJobQueue, S3ObjectStore
from services.api.qwen_ocr import Qwen35OCRProvider, QwenOCRError
from services.api.store import NotFoundError
from services.api.worker_pipeline import ProcessingError, WorkerPipeline


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def retry_backoff_seconds(base_seconds: float, attempt: int, *, cap_seconds: float = 30.0) -> float:
    """Return bounded exponential delay for a retry without exposing payloads."""
    if base_seconds <= 0 or attempt <= 0:
        return 0.0
    return min(float(cap_seconds), base_seconds * (2 ** max(0, attempt - 1)))


class WorkerRuntime:
    def __init__(self) -> None:
        settings = ProviderSettings.from_environment()
        required = {
            "DATABASE_URL": settings.postgres_dsn,
            "S3_BUCKET": settings.s3_bucket,
            "S3_ENDPOINT": settings.s3_endpoint,
            "REDIS_URL": settings.redis_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("worker settings missing: " + ", ".join(missing))
        self.store = PostgresMetadataStore(settings.postgres_dsn or "")
        try:
            self.objects = S3ObjectStore(settings.s3_bucket or "", endpoint_url=settings.s3_endpoint, region_name=settings.s3_region)
            self.queue = RedisJobQueue(settings.redis_url or "", queue_name=settings.redis_queue)
        except Exception:
            self.store.close()
            raise
        ocr_provider_name = os.getenv("OCR_PROVIDER", "fixture").strip().lower()
        ocr_provider = None
        provider_label = ""
        if ocr_provider_name in {"qwen3.5-ocr", "qwen35-ocr", "qwen-vl-ocr", "qwen-vl-ocr-latest", "bailian"}:
            try:
                provider = Qwen35OCRProvider.from_environment()
            except QwenOCRError:
                # Fail closed at startup instead of silently processing with
                # fixtures when an explicitly selected provider is invalid.
                self.store.close()
                raise
            ocr_provider = provider.extract
            provider_label = provider.provider_name
        elif ocr_provider_name not in {"fixture", "local"}:
            self.store.close()
            raise RuntimeError("unsupported OCR_PROVIDER")
        self.pipeline = WorkerPipeline(
            self.store,
            self.objects,
            data_classification=os.getenv("STAGING_DATA_CLASSIFICATION", "deidentified"),
            ocr_provider=ocr_provider,
            ocr_provider_name=provider_label,
        )
        self.consumer_enabled = _enabled(os.getenv("WORKER_CONSUMER_ENABLED", "1"))
        default_mode = f"queue-consumer-{ocr_provider_name}" if provider_label else ("queue-consumer-fixture-ocr" if self.consumer_enabled else "fixture-health-only")
        self.mode = os.getenv("WORKER_MODE", default_mode)
        self.max_attempts = max(1, int(os.getenv("WORKER_MAX_ATTEMPTS", "3")))
        try:
            self.retry_backoff_base_seconds = max(0.0, float(os.getenv("WORKER_RETRY_BACKOFF_SECONDS", "1")))
        except ValueError:
            self.retry_backoff_base_seconds = 1.0
        # The API writes the Redis message just before its metadata row.  A
        # fast consumer can therefore observe a job a few milliseconds before
        # PostgreSQL commits it.  Retry that narrow race, while bounding truly
        # stale/unknown messages so they cannot poison the queue forever.
        self.max_metadata_wait_attempts = max(1, int(os.getenv("WORKER_METADATA_WAIT_ATTEMPTS", "3")))
        self.lease_seconds = max(1, int(os.getenv("WORKER_LEASE_SECONDS", "60")))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def dependencies_ready(self) -> bool:
        return self.store.is_ready() and self.objects.is_ready() and self.queue.is_ready()

    def start(self) -> None:
        if not self.consumer_enabled:
            return
        self._thread = threading.Thread(target=self.consume_forever, name="patient-app-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.store.close()

    def _mark_retry(self, job: UploadProcessingJob, code: str, *, retryable: bool = True) -> bool:
        if retryable and job.attempt < self.max_attempts:
            self.store.save_resource("jobs", replace(job, status=JobStatus.QUEUED, error_code=code))
            return True
        failed = replace(job, status=JobStatus.FAILED, error_code=code)
        self.store.save_resource("jobs", failed)
        try:
            document = self.store.get_resource("documents", job.document_id)
            if document.status != DocumentStatus.FAILED:
                self.store.save_resource(
                    "documents",
                    replace(document, status=DocumentStatus.FAILED, version=document.version + 1),
                    expected_version=document.version,
                )
        except Exception:
            pass
        return False

    def consume_forever(self) -> None:
        while not self._stop.is_set():
            try:
                message = self.queue.claim(block_seconds=1, lease_seconds=self.lease_seconds)
            except Exception:
                self._stop.wait(1)
                continue
            if message is None:
                continue
            job_id = str(message["job_id"])
            try:
                self.pipeline.process(job_id)
                self.queue.ack(message)
            except ProcessingError as exc:
                try:
                    job = self.store.get_resource("jobs", job_id)
                    retry = self._mark_retry(job, exc.code, retryable=exc.retryable)
                    if retry:
                        self._stop.wait(retry_backoff_seconds(self.retry_backoff_base_seconds, job.attempt))
                        self.queue.requeue(message)
                    else:
                        self.queue.ack(message)
                except Exception:
                    # A job deleted before delivery is no longer actionable;
                    # acknowledge the metadata-only message to avoid a poison
                    # item occupying the processing list forever.
                    try:
                        self.queue.ack(message)
                    except Exception:
                        continue
            except NotFoundError:
                payload = dict(message.get("payload") or {})
                try:
                    metadata_wait_attempt = int(payload.get("metadata_wait_attempt", "0")) + 1
                except (TypeError, ValueError):
                    metadata_wait_attempt = self.max_metadata_wait_attempts + 1
                if metadata_wait_attempt <= self.max_metadata_wait_attempts:
                    payload["metadata_wait_attempt"] = str(metadata_wait_attempt)
                    try:
                        # Omit the old raw message so RedisJobQueue rebuilds a
                        # message containing the incremented delivery count.
                        self.queue.requeue({"job_id": job_id, "payload": payload})
                    except Exception:
                        try:
                            self.queue.ack(message)
                        except Exception:
                            continue
                else:
                    try:
                        self.queue.ack(message)
                    except Exception:
                        continue
            except Exception:
                try:
                    job = self.store.get_resource("jobs", job_id)
                    retry = self._mark_retry(job, "PROCESSING_FAILED")
                    if retry:
                        self._stop.wait(retry_backoff_seconds(self.retry_backoff_base_seconds, job.attempt))
                        self.queue.requeue(message)
                    else:
                        self.queue.ack(message)
                except Exception:
                    try:
                        self.queue.ack(message)
                    except Exception:
                        continue


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "patient-app-staging-worker/2"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path not in {"/healthz", "/readyz"}:
            self._write(404, {"status": "not_found"})
            return
        runtime: WorkerRuntime | None = getattr(self.server, "runtime", None)
        ready = bool(runtime and runtime.dependencies_ready())
        if self.path == "/readyz" and not ready:
            self._write(503, {"status": "not_ready", "service": "worker"})
            return
        self._write(
            200,
            {
                "status": "ok",
                "service": "worker",
                "mode": runtime.mode if runtime else os.getenv("WORKER_MODE", "provider-consumer"),
                "consumer_enabled": bool(runtime and runtime.consumer_enabled),
                "data_classification": os.getenv("STAGING_DATA_CLASSIFICATION", "deidentified"),
            },
        )

    def log_message(self, *_: object) -> None:
        return

    def _write(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    runtime = WorkerRuntime()
    port = int(os.getenv("WORKER_PORT", "8081"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.runtime = runtime  # type: ignore[attr-defined]
    runtime.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.stop()


if __name__ == "__main__":
    main()
