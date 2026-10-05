# Real staging composition

This directory defines a reproducible, synthetic/de-identified staging
composition. It starts PostgreSQL, a pinned LocalStack-compatible S3 persistence
image, Redis, the API HTTP adapter wired to the checked-in provider adapters,
and a Redis-backed worker consumer. The object-store image keeps S3 state in
the named volume and is pinned by digest for repeatable local runs. The API
applies the checked-in PostgreSQL migration on startup and fails readiness when
PostgreSQL, the S3 service, or Redis is unavailable. A remote staging
deployment can set `S3_ENDPOINT` to an approved S3-compatible service.

The default worker mode is `queue-consumer-fixture-ocr` with bounded retries and
lease recovery. Plain-text synthetic fixtures use the explicit local-text
ingest path; PDF and image inputs require `pdftotext` or `tesseract` in the
worker image and report `OCR_PROVIDER_UNAVAILABLE` when those providers are not
installed. A ready worker therefore confirms queue consumption and dependency
health, while the acceptance report still labels fixture processing separately
from provider OCR/AI results.

The worker can opt into the server-side Alibaba Cloud Model Studio Qwen3.5-OCR
adapter with values supplied only through the ignored staging environment file or
an external secret manager:

```dotenv
OCR_PROVIDER=qwen3.5-ocr
DASHSCOPE_BASE_URL=https://<workspace>.<region>.maas.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.5-ocr
DASHSCOPE_OCR_TASK=text_recognition
DASHSCOPE_API_KEY=<secret-managed-value>
WORKER_MODE=queue-consumer-qwen3.5-ocr
STAGING_DATA_CLASSIFICATION=deidentified
```

The key is read by the Worker only and is never returned to iOS or included in
request bodies. The adapter requires HTTPS, rejects invalid configuration at
startup, and currently accepts image inputs through the OpenAI-compatible chat
endpoint. PDF input fails closed until a separately reviewed server-side file
parsing/rasterization path is enabled. This local staging mode remains limited to
synthetic or de-identified data; an external provider contract and approved data
processing terms are required before any real patient data is considered.

## Start

Create a local env file from the checked-in example and replace all placeholder
secrets using the approved secret manager or shell environment:

```sh
cp .env.staging.example .env.staging
chmod 600 .env.staging
scripts/staging/compose-up.sh
```

The helper requires `STAGING_ENV_FILE` when the env file lives elsewhere. It
never prints secret values. API health is available at
`http://localhost:58000/healthz`; worker health is available at
`http://localhost:58001/healthz` with the example ports.

Stop the services without deleting data with:

```sh
scripts/staging/compose-down.sh
```

Set `STAGING_REMOVE_VOLUMES=1` only when synthetic staging data should be
deleted. The default is to preserve the three named volumes.

## Validation

Validate interpolation without starting containers:

```sh
docker compose --env-file .env.staging.example \
  --file infra/staging/compose.yaml config --quiet
scripts/staging/test-compose.sh
```

When Docker Desktop/daemon is unavailable, this config check remains useful;
`compose-up.sh` should be run only after the daemon is running. The API image
uses deterministic synthetic fixtures and `AI_PROVIDER=stub` by default. No
real patient content, tokens, production URLs, or cloud credentials belong in
this repository.
