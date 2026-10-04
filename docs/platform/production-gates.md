# Pre-production gate manifest

`scripts/production_gate.py` evaluates the evidence register defined by ADR-0003 D1–D8. It is a local, repeatable check; it does not call a cloud provider, identity service or telemetry sink. The input register contains only fixed evidence identifiers and boolean states. The output contains the ADR baseline, commit, mode, per-decision status, fixed missing-evidence identifiers and a Go/Pause/No-Go result. It never copies input paths, filenames, evidence text, PHI or tokens.

## Production mode

Prepare a restricted evidence register with this envelope:

```json
{
  "input_schema": "patient-app-platform/production-gate-input",
  "schema_version": "1.0.0",
  "decisions": {
    "D1": {"evidence": {"pilot_scope": true, "role_scope": true, "product_owner_signoff": true}},
    "D2": {"evidence": {"service_entity": true, "us_region": true, "baa_dpa": true, "compliance_owner_signoff": true}}
  }
}
```

The complete register must contain the fixed keys for D1–D8 from ADR-0003. The gate rejects missing, extra or non-boolean keys. Evidence must include the service entity, US region, BAA/DPA and compliance sign-off (D2); protected-cache and purge evidence (D4); cross-store deletion/legal-hold evidence (D5); scoped share and revoke re-check evidence (D6); telemetry redaction and key-rotation evidence (D7); and all four owner sign-offs plus the evidence register and incident exercise (D8). The exact requirement names are in the script and are intentionally closed to prevent an ambiguous “pass.”

```text
python3 scripts/production_gate.py \
  --mode production \
  --evidence restricted/adr-0003-evidence.json \
  --output artifacts/production-gate.json
```

A complete register produces `go` with `production_phi_allowed: true` and exits 0. Any missing/invalid evidence produces `no-go`, lists only the fixed decision/evidence IDs, writes the manifest, and exits 1. No-Go is the expected result until product and compliance/security owners attach their signed evidence; a passing software test cannot override it.

## Synthetic build mode

Synthetic/de-identified development can generate an explicit pause manifest without an evidence file:

```text
python3 scripts/production_gate.py \
  --mode synthetic \
  --output artifacts/production-gate-synthetic.json
```

This exits 0 with every decision marked `pause` and `production_phi_allowed: false`. It makes the safe development state machine visible without implying that production PHI is approved.

## Regression check and handling

Run `bash scripts/test-production-gate.sh`. It covers a complete Go register, missing BAA/DPA/cache/deletion/share/redaction/key-rotation/owner-sign-off evidence, and synthetic Pause mode. Keep the evidence register in the approved restricted store; commit only the script and redacted manifest schema/status, never the register or evidence content.
