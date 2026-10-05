#!/usr/bin/env python3
"""Configure the server-side Bailian Qwen3.5-OCR staging worker.

The API key is read from a hidden prompt and written only to the ignored local
environment file. It is never printed, committed, or sent to iOS.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
from pathlib import Path


REGION_HOSTS = {
    "us-east-1": "{workspace}.us-east-1.maas.aliyuncs.com",
    "ap-southeast-1": "{workspace}.ap-southeast-1.maas.aliyuncs.com",
    "cn-beijing": "{workspace}.cn-beijing.maas.aliyuncs.com",
    "ap-northeast-1": "{workspace}.ap-northeast-1.maas.aliyuncs.com",
    "eu-central-1": "{workspace}.eu-central-1.maas.aliyuncs.com",
    "cn-hongkong": "{workspace}.cn-hongkong.maas.aliyuncs.com",
}
WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,127}$")


def _env_path(value: str | None) -> Path:
    return Path(value or os.getenv("STAGING_ENV_FILE", ".env.staging")).expanduser()


def _read_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_values(path: Path, updates: dict[str, str]) -> None:
    if not path.exists():
        example = path.with_name(".env.staging.example")
        if not example.exists():
            raise SystemExit(f"environment template not found: {example}")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    written: set[str] = set()
    output: list[str] = []
    for raw in lines:
        line = raw.strip()
        key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith("#") else ""
        if key in updates:
            output.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            output.append(raw)
    for key, value in updates.items():
        if key not in written:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure backend-only Bailian Qwen3.5-OCR staging")
    parser.add_argument("--region", choices=sorted(REGION_HOSTS), required=True)
    parser.add_argument("--workspace-id", required=True, help="Bailian workspace ID, not a secret")
    parser.add_argument("--env-file", help="ignored env file; defaults to STAGING_ENV_FILE or .env.staging")
    parser.add_argument("--keep-existing-key", action="store_true", help="reuse an existing local key without prompting")
    args = parser.parse_args()

    if not WORKSPACE_RE.fullmatch(args.workspace_id):
        parser.error("workspace ID must contain only letters, digits, underscore, or hyphen")
    path = _env_path(args.env_file)
    existing = _read_values(path)
    key = existing.get("DASHSCOPE_API_KEY", "") if args.keep_existing_key else getpass.getpass("DASHSCOPE_API_KEY (hidden input): ").strip()
    if not key:
        parser.error("a non-empty API key is required; use --keep-existing-key only when .env.staging already contains one")
    host = REGION_HOSTS[args.region].format(workspace=args.workspace_id)
    updates = {
        "OCR_PROVIDER": "qwen3.5-ocr",
        "WORKER_MODE": "queue-consumer-qwen3.5-ocr",
        "DASHSCOPE_API_KEY": key,
        "DASHSCOPE_BASE_URL": f"https://{host}/compatible-mode/v1",
        "DASHSCOPE_MODEL": "qwen3.5-ocr",
        "DASHSCOPE_OCR_TASK": "text_recognition",
        "DASHSCOPE_MAX_PDF_PAGES": existing.get("DASHSCOPE_MAX_PDF_PAGES", "20"),
        "DASHSCOPE_PDF_RASTER_DPI": existing.get("DASHSCOPE_PDF_RASTER_DPI", "150"),
        "STAGING_DATA_CLASSIFICATION": existing.get("STAGING_DATA_CLASSIFICATION", "deidentified") or "deidentified",
    }
    if updates["STAGING_DATA_CLASSIFICATION"] not in {"synthetic", "deidentified"}:
        parser.error("STAGING_DATA_CLASSIFICATION must remain synthetic or deidentified")
    _write_values(path, updates)
    print(f"Configured backend OCR provider for region {args.region} in {path} (key not displayed).")
    print("The key remains in the ignored env file and is read only by the staging Worker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
