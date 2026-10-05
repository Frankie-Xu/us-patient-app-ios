#!/usr/bin/env bash
set -euo pipefail

python_bin="${PYTHON_BIN:-python3}"
"$python_bin" - <<'PY'
from scripts.production_config import ConfigParseError, load_env_file, validate_config

local = validate_config({
    "APP_ENV": "local",
    "API_BASE_URL": "http://localhost:8000",
    "OBJECT_STORAGE_BUCKET": "local",
    "AI_PROVIDER": "stub",
})
assert local.valid, local.errors

staging = validate_config({
    "APP_ENV": "staging",
    "API_BASE_URL": "https://api.example.test",
    "OBJECT_STORAGE_BUCKET": "staging-bucket",
    "OBJECT_STORAGE_REGION": "us-test-1",
    "AI_PROVIDER": "stub",
    "IDENTITY_ISSUER": "https://identity.example.test",
    "IDENTITY_AUDIENCE": "patient-app",
    "DATABASE_URL_REF": "ref://staging/database",
    "QUEUE_NAME": "processing",
    "KMS_KEY_ID_REF": "ref://staging/kms",
    "SECRET_REF_PREFIX": "ref://staging/",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "https://telemetry.example.test",
})
assert staging.valid, staging.errors

missing = validate_config({"APP_ENV": "production", "API_BASE_URL": "http://insecure.example.test"})
assert "https_required:API_BASE_URL" in missing.errors
assert any(error == "missing:DATABASE_URL_REF" for error in missing.errors)

direct_secret = validate_config({
    "APP_ENV": "local",
    "API_BASE_URL": "http://localhost:8000",
    "OBJECT_STORAGE_BUCKET": "local",
    "AI_PROVIDER": "stub",
    "DATABASE_URL": "postgresql://user:password@host/database",
})
assert "direct_secret_forbidden:DATABASE_URL" in direct_secret.errors

with __import__("tempfile").NamedTemporaryFile("w+", encoding="utf-8") as handle:
    handle.write("APP_ENV=local\nAPP_ENV=staging\n")
    handle.flush()
    try:
        load_env_file(handle.name)
    except ConfigParseError:
        pass
    else:
        raise AssertionError("duplicate configuration names must fail closed")

print("production configuration regression passed")
PY
