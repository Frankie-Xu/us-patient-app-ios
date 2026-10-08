#!/usr/bin/env python3
"""Make an Xcode archive exportable on toolchains that omit archive metadata."""

from __future__ import annotations

import argparse
import plistlib
import subprocess
from pathlib import Path


def _plist(path: Path) -> dict:
    return plistlib.loads(path.read_bytes())


def _codesign_identity(app: Path) -> str:
    result = subprocess.run(
        ["codesign", "-dvv", str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    for line in result.stderr.splitlines():
        if line.startswith("Authority="):
            return line.removeprefix("Authority=")
    return ""


def _profile_metadata(app: Path) -> tuple[str, str]:
    profile = app / "embedded.mobileprovision"
    if not profile.exists():
        return "", ""
    decoded = subprocess.run(
        ["security", "cms", "-D", "-i", str(profile)],
        check=True,
        capture_output=True,
    )
    values = plistlib.loads(decoded.stdout)
    team_ids = values.get("TeamIdentifier") or []
    return (team_ids[0] if team_ids else "", values.get("Name", ""))


def prepare(archive: Path) -> bool:
    info_path = archive / "Info.plist"
    products = archive / "Products" / "Applications"
    apps = sorted(products.glob("*.app"))
    if not info_path.exists() or len(apps) != 1:
        raise SystemExit("archive must contain one application and an Info.plist")

    info = _plist(info_path)
    app = apps[0]
    app_info = _plist(app / "Info.plist")
    team_id, profile_name = _profile_metadata(app)
    identity = _codesign_identity(app)
    application_properties = {
        "ApplicationPath": f"Applications/{app.name}",
        "CFBundleIdentifier": app_info.get("CFBundleIdentifier", ""),
        "CFBundleShortVersionString": app_info.get("CFBundleShortVersionString", ""),
        "CFBundleVersion": app_info.get("CFBundleVersion", ""),
        "SigningIdentity": identity,
        "Team": team_id,
        "TeamID": team_id,
    }
    if profile_name:
        application_properties["ProvisioningProfile"] = profile_name

    if info.get("ApplicationProperties") == application_properties:
        return False
    info["ApplicationProperties"] = application_properties
    info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path, help="Path to the .xcarchive")
    args = parser.parse_args()
    changed = prepare(args.archive)
    print("archive metadata prepared" if changed else "archive metadata already present")


if __name__ == "__main__":
    main()
