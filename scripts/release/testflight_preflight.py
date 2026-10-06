#!/usr/bin/env python3
"""Validate deterministic evidence produced by an iOS TestFlight release.

The preflight consumes an archive/export evidence directory. It checks metadata,
release/signing placeholders, resources, dSYMs and crash-monitoring setup without
requiring an Apple credential. Reports contain statuses, stable codes and safe
relative paths only; file contents and credential-like values are never printed.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "patient-app-platform/testflight-preflight"
SCHEMA_VERSION = "1.0.0"
DEFAULT_LOCALES = ("en", "zh-Hans")
_MAX_TEXT_BYTES = 2 * 1024 * 1024
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][0-9A-Za-z.-]+)?$")
_BUILD_RE = re.compile(r"^[0-9]+$")
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|private[_-]?key|token)\s*[:=]\s*[\"']?[A-Za-z0-9_+=/.-]{16,}"),
)
_METADATA_NAMES = {"info.plist", "metadata.json", "version.json", "build.json", "release-info.json"}
_RELEASE_NAMES = {
    "exportoptions.plist",
    "export-options.plist",
    "release-config.json",
    "build-settings.json",
    "signing.json",
    "signing.plist",
    "release.xcconfig",
}
_CRASH_NAMES = {
    "sentry.properties",
    "sentry-cli.properties",
    "crashlytics.properties",
    "firebase_app_id_file.json",
    "crash-monitoring.json",
    "crash-monitoring.plist",
}


@dataclass(frozen=True)
class Finding:
    category: str
    status: str
    code: str
    paths: tuple[str, ...] = ()
    details: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "category": self.category,
            "status": self.status,
            "code": self.code,
        }
        if self.paths:
            value["paths"] = list(self.paths)
        if self.details:
            value["details"] = list(self.details)
        return value


def _safe_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted((path for path in root.rglob("*") if path.is_file() and not path.is_symlink()), key=lambda p: p.as_posix())


def _read_text(path: Path) -> str:
    try:
        data = path.read_bytes()[:_MAX_TEXT_BYTES]
    except OSError:
        return ""
    if b"\x00" in data[:4096]:
        return ""
    return data.decode("utf-8", errors="replace")


def _mapping(path: Path) -> dict[str, Any] | None:
    try:
        if path.suffix.lower() == ".plist":
            value = plistlib.loads(path.read_bytes())
        elif path.suffix.lower() == ".json":
            value = json.loads(_read_text(path))
        else:
            return None
    except (OSError, ValueError, plistlib.InvalidFileException, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _flatten(value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), str(child) if not isinstance(child, (dict, list)) else ""
            yield from _flatten(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten(child)


def _metadata_candidates(root: Path) -> list[Path]:
    return [path for path in _files(root) if path.name.lower() in _METADATA_NAMES]


def _extract_metadata(root: Path) -> tuple[str | None, str | None, list[Path]]:
    version: str | None = None
    build: str | None = None
    used: list[Path] = []
    for path in _metadata_candidates(root):
        value = _mapping(path)
        if value is None:
            continue
        pairs = list(_flatten(value))
        values = {key.lower(): raw for key, raw in pairs if raw}
        candidate_version = next((values[key] for key in ("cfbundleshortversionstring", "version", "marketing_version", "short_version") if values.get(key)), None)
        candidate_build = next((values[key] for key in ("cfbundleversion", "build", "build_number", "buildnumber") if values.get(key)), None)
        if candidate_version is not None or candidate_build is not None:
            used.append(path)
        if version is None and candidate_version is not None:
            version = candidate_version.strip()
        if build is None and candidate_build is not None:
            build = candidate_build.strip()
        if version is not None and build is not None:
            break
    return version, build, used


def _check_version(root: Path) -> Finding:
    version, build, used = _extract_metadata(root)
    paths = tuple(_safe_relative(root, path) for path in used)
    if not version:
        return Finding("version", "failed", "missing_version", paths)
    if not _VERSION_RE.fullmatch(version):
        return Finding("version", "failed", "invalid_version", paths)
    if not build:
        return Finding("version", "failed", "missing_build_number", paths)
    if not _BUILD_RE.fullmatch(build) or int(build) <= 0:
        return Finding("version", "failed", "invalid_build_number", paths)
    return Finding("version", "passed", "version_build_comparable", paths)


def _release_candidates(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in _files(root):
        lower = path.name.lower()
        if lower in _RELEASE_NAMES or lower.endswith(".xcconfig"):
            result.append(path)
    return result


def _has_release_marker(text: str, mapping: dict[str, Any] | None) -> bool:
    if re.search(r"(?i)\b(?:configuration|build[_-]?configuration|config)\s*[:=]\s*[\"']?release\b", text):
        return True
    if mapping is not None:
        for key, value in _flatten(mapping):
            if key.lower() in {"configuration", "buildconfiguration", "build_configuration", "config"} and value.strip().lower() == "release":
                return True
    return False


def _check_release(root: Path, dry_run: bool) -> Finding:
    candidates = _release_candidates(root)
    if not candidates:
        return Finding("release_configuration", "failed", "missing_release_configuration")
    release_paths = [path for path in candidates if _has_release_marker(_read_text(path), _mapping(path))]
    if not release_paths:
        return Finding("release_configuration", "failed", "release_configuration_not_found", tuple(_safe_relative(root, path) for path in candidates))
    signing_markers = re.compile(r"(?i)(?:code[_-]?sign|signing|development_team|team[_-]?id|provisioning|certificate)")
    placeholder_markers = re.compile(r"(?i)(?:placeholder|example|automatic|dry[_-]?run|todo|replace[_-]?me)")
    signing_paths = [path for path in candidates if signing_markers.search(_read_text(path))]
    if not signing_paths:
        return Finding("release_configuration", "failed", "missing_signing_placeholder", tuple(_safe_relative(root, path) for path in release_paths))
    if dry_run and not any(placeholder_markers.search(_read_text(path)) for path in signing_paths):
        return Finding("release_configuration", "failed", "signing_placeholder_not_found", tuple(_safe_relative(root, path) for path in signing_paths))
    return Finding("release_configuration", "passed", "release_and_signing_placeholder_found", tuple(_safe_relative(root, path) for path in release_paths))


def _check_secrets(root: Path) -> Finding:
    matches: list[str] = []
    for path in _files(root):
        text = _read_text(path)
        if text and any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            matches.append(_safe_relative(root, path))
    if matches:
        return Finding("credential_hygiene", "failed", "credential_like_content_detected", tuple(matches))
    return Finding("credential_hygiene", "passed", "no_credential_like_content")


def _check_resources(root: Path, locales: tuple[str, ...]) -> Finding:
    info = [path for path in _files(root) if path.name.lower() == "info.plist"]
    if not info:
        return Finding("resources", "failed", "missing_info_plist")
    found: set[str] = set()
    for path in _files(root):
        for parent in path.parents:
            if parent.name.lower().endswith(".lproj"):
                locale = parent.name[:-6]
                if path.name.lower() in {"localizable.strings", "localizable.xcstrings"}:
                    found.add(locale)
                break
    missing = tuple(locale for locale in locales if locale not in found)
    paths = tuple(_safe_relative(root, path) for path in info)
    if missing:
        return Finding("resources", "failed", "missing_localization", paths, missing)
    return Finding("resources", "passed", "info_plist_and_localization_found", paths)


def _check_symbols(root: Path) -> Finding:
    symbols: list[Path] = []
    for path in _files(root):
        if ".dSYM/Contents/Resources/DWARF/" in path.as_posix():
            symbols.append(path)
    if not symbols:
        return Finding("symbols", "failed", "missing_dsym")
    return Finding("symbols", "passed", "dsym_found", tuple(_safe_relative(root, path) for path in symbols))


def _check_crash_monitoring(root: Path) -> Finding:
    candidates = []
    for path in _files(root):
        lower = path.name.lower()
        if lower in _CRASH_NAMES or ("crash" in lower and path.suffix.lower() in {".json", ".plist", ".properties", ".xcconfig"}):
            candidates.append(path)
    if not candidates:
        return Finding("crash_monitoring", "failed", "missing_crash_monitoring_config")
    return Finding("crash_monitoring", "passed", "crash_monitoring_config_found", tuple(_safe_relative(root, path) for path in candidates))


def _manifest(root: Path, dry_run: bool, locales: tuple[str, ...]) -> dict[str, Any]:
    checks = [
        _check_version(root),
        _check_release(root, dry_run),
        _check_secrets(root),
        _check_resources(root, locales),
        _check_symbols(root),
        _check_crash_monitoring(root),
    ]
    failed = [check.category for check in checks if check.status == "failed"]
    missing = [check.as_dict() for check in checks if check.status == "failed"]
    return {
        "manifest_schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "mode": "dry-run" if dry_run else "archive",
        "evidence_root": ".",
        "checks": {check.category: check.as_dict() for check in checks},
        "missing_items": missing,
        "overall": {"status": "failed" if failed else "passed", "failed_categories": failed},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default="artifacts/testflight-evidence", help="archive/export evidence directory")
    parser.add_argument("--output", default="artifacts/testflight-preflight.json", help="redacted JSON report path")
    parser.add_argument("--locales", default=",".join(DEFAULT_LOCALES), help="comma-separated required .lproj locales")
    parser.add_argument("--dry-run", action="store_true", help="credential-free CI validation using placeholders")
    args = parser.parse_args(argv)
    root = Path(args.evidence_dir).expanduser().resolve()
    locales = tuple(item.strip() for item in args.locales.split(",") if item.strip())
    if not locales:
        parser.error("at least one locale is required")
    report = _manifest(root, args.dry_run, locales)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"testflight preflight: {report['overall']['status']}")
    return 0 if report["overall"]["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
