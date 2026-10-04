# Contract and evidence gates

Phase 12 adds two offline checks to the frozen OpenAPI and release workflow. Both checks are deterministic and credential-free; they never call a cloud service or print request data, source paths, PHI, or tokens.

## OpenAPI drift

`packages/contracts/openapi.yaml` is the contract source. `packages/contracts/contract.routes.json` is a reviewed inventory of its method/path pairs. Run:

```text
bash scripts/check-openapi.sh
bash scripts/check-contract-drift.sh
bash scripts/test-contract-drift.sh
```

The drift checker normalizes the OpenAPI `paths` object and compares it with the sorted inventory. A route or method change fails until the inventory is updated in the same review. Diagnostics emit only pass/fail and the aggregate route count; the inventory is the reviewable contract delta.

## Redacted evidence

`production_gate.py --mode synthetic` creates a Pause manifest for development. It never grants production PHI access. The release-evidence job records this synthetic gate as an explicit `synthetic_gate` group, then runs `check_privacy_evidence.py` over the release and production-gate manifests:

```text
python3 scripts/production_gate.py --mode synthetic --output artifacts/production-gate-synthetic.json
python3 scripts/release_evidence.py --from-ci --output artifacts/release-evidence.json
python3 scripts/check_privacy_evidence.py \
  --input artifacts/release-evidence.json \
  --input artifacts/production-gate-synthetic.json \
  --output artifacts/privacy-evidence.json
```

The privacy checker accepts only the known evidence schemas, rejects sensitive key/value patterns and path-like material, and writes fixed violation codes without echoing the offending content. Run `bash scripts/test-privacy-evidence.sh` for pass/fail and leak regression coverage. Generated artifacts are short-retention CI evidence; restricted production evidence registers remain outside the repository.
