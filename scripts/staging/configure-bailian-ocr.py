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
import subprocess
import tempfile
from pathlib import Path


REGION_HOSTS = {
    "us-east-1": "{workspace}.us-east-1.maas.aliyuncs.com",
    "ap-southeast-1": "{workspace}.ap-southeast-1.maas.aliyuncs.com",
    "cn-beijing": "{workspace}.cn-beijing.maas.aliyuncs.com",
    "ap-northeast-1": "{workspace}.ap-northeast-1.maas.aliyuncs.com",
    "eu-central-1": "{workspace}.eu-central-1.maas.aliyuncs.com",
    "cn-hongkong": "{workspace}.cn-hongkong.maas.aliyuncs.com",
}
REGION_DEFAULT_MODELS = {
    "us-east-1": "qwen-vl-ocr",
    "ap-southeast-1": "qwen-vl-ocr",
    "cn-beijing": "qwen3.5-ocr",
    "ap-northeast-1": "qwen-vl-ocr",
    "eu-central-1": "qwen-vl-ocr",
    "cn-hongkong": "qwen-vl-ocr",
}
WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,127}$")


def _valid_key(key: str) -> bool:
    return key.startswith("sk-") and 16 <= len(key) <= 512 and not any(character.isspace() for character in key)


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
    if path.is_symlink():
        raise SystemExit("refusing to write credentials through a symlink")
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        example = path.with_name(".env.staging.example")
        if not example.exists():
            raise SystemExit(f"environment template not found: {example}")
        path.parent.mkdir(parents=True, exist_ok=True)
        content = example.read_text(encoding="utf-8")
    lines = content.splitlines()
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
    descriptor, temporary_path = tempfile.mkstemp(prefix=".env.staging-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(output) + "\n")
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _check_destination(path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    resolved = path.resolve()
    if resolved.is_relative_to(root):
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--quiet", "--", str(resolved)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode != 0:
            raise SystemExit("Credential destination inside the repository must be Git-ignored; configuration was not changed.")


def _clipboard_key() -> str:
    try:
        result = subprocess.run(
            ["pbpaste"], check=True, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=5,
        )
        key = result.stdout.decode("utf-8").strip()
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        raise SystemExit("Cannot read the local clipboard; configuration was not changed.") from None
    if not _valid_key(key):
        raise SystemExit("Clipboard does not contain a standard Bailian API key. Copy the key again; configuration was not changed.")
    return key


def _dialog_key() -> str:
    prompt = (
        'text returned of (display dialog "请粘贴百炼 API Key。密钥只保存到本机后端配置，不进入聊天或 Git。" '
        'default answer "" with hidden answer buttons {"取消", "保存到后端"} '
        'default button "保存到后端" cancel button "取消" with title "百炼后端 API Key 配置")'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", prompt], check=True, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=600,
        )
        return result.stdout.decode("utf-8").strip()
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        raise SystemExit("Local key dialog cancelled or unavailable; configuration was not changed.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure backend-only Bailian Qwen3.5-OCR staging")
    parser.add_argument("--region", choices=sorted(REGION_HOSTS), required=True)
    parser.add_argument("--workspace-id", required=True, help="Bailian workspace ID, not a secret")
    parser.add_argument("--env-file", help="ignored env file; defaults to STAGING_ENV_FILE or .env.staging")
    parser.add_argument("--model", choices=("qwen-vl-ocr", "qwen-vl-ocr-latest", "qwen3.5-ocr"), help="override the model supported in the selected region")
    key_sources = parser.add_mutually_exclusive_group()
    key_sources.add_argument("--keep-existing-key", action="store_true", help="reuse an existing local key without prompting")
    key_sources.add_argument("--key-from-clipboard", action="store_true", help="import the copied key locally using macOS pbpaste; never print it")
    key_sources.add_argument("--key-from-dialog", action="store_true", help="open a macOS hidden-input dialog to paste the key")
    args = parser.parse_args()

    if not WORKSPACE_RE.fullmatch(args.workspace_id):
        parser.error("workspace ID must contain only letters, digits, underscore, or hyphen")
    path = _env_path(args.env_file)
    _check_destination(path)
    existing = _read_values(path)
    if args.keep_existing_key:
        key = existing.get("DASHSCOPE_API_KEY", "")
    elif args.key_from_clipboard:
        key = _clipboard_key()
    elif args.key_from_dialog:
        key = _dialog_key()
    else:
        try:
            key = getpass.getpass("DASHSCOPE_API_KEY (hidden input): ").strip()
        except (KeyboardInterrupt, EOFError):
            raise SystemExit("Key entry cancelled; configuration was not changed.") from None
    if not key:
        parser.error("a non-empty API key is required; use --keep-existing-key only when .env.staging already contains one")
    if not _valid_key(key):
        parser.error("input is not a standard Bailian API key; configuration was not changed")
    host = REGION_HOSTS[args.region].format(workspace=args.workspace_id)
    model = args.model or REGION_DEFAULT_MODELS[args.region]
    updates = {
        "OCR_PROVIDER": model,
        "WORKER_MODE": f"queue-consumer-{model}",
        "DASHSCOPE_API_KEY": key,
        "DASHSCOPE_BASE_URL": f"https://{host}/compatible-mode/v1",
        "DASHSCOPE_MODEL": model,
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
