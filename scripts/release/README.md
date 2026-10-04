# TestFlight evidence preflight

`testflight_preflight.py` validates the redacted evidence directory produced by an
Xcode archive/export. It is intentionally credential-free: signing files must use
placeholders, and token or private-key shaped content makes the check fail without
printing the matched value.

```sh
scripts/release/testflight-preflight.sh \
  --evidence-dir artifacts/testflight-evidence \
  --output artifacts/testflight-preflight.json \
  --dry-run
```

The default required locales are `en` and `zh-Hans`; pass `--locales en,zh-Hans`
to make the requirement explicit. The evidence directory must contain:

- an `Info.plist` (or JSON metadata) with a non-empty, comparable marketing
  version and positive numeric build number;
- a Release build configuration and signing placeholder (`Automatic`,
  `TEAM_ID_PLACEHOLDER`, or an equivalent explicit placeholder);
- `Localizable.strings` or `Localizable.xcstrings` under each required `.lproj`;
- at least one DWARF file under `*.dSYM/Contents/Resources/DWARF/`; and
- a crash-monitoring configuration such as `crash-monitoring.json`,
  `sentry.properties`, or `crashlytics.properties`.

The JSON report is deterministic and contains stable category/code/path findings:
`version`, `release_configuration`, `credential_hygiene`, `resources`, `symbols`,
and `crash_monitoring`. Missing or invalid evidence returns exit code `1`; a
passing report returns `0`. File contents, credential values, and patient data are
never included in the report or stdout.
