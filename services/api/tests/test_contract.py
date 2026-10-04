from pathlib import Path
import unittest


class ContractTests(unittest.TestCase):
    def test_openapi_contract_declares_required_boundaries(self) -> None:
        path = Path(__file__).parents[3] / "packages" / "contracts" / "openapi.yaml"
        text = path.read_text(encoding="utf-8")
        for marker in (
            "openapi: 3.1.0",
            "x-contract-status: frozen",
            "\"/v1/documents\":",
            "\"/v1/facts\":",
            "\"/v1/shares/{shareId}/revoke\":",
            "\"/v1/shared/{token}\":",
            "source_ref:",
            "source_type:",
            "confidence:",
            "review_status:",
            "Idempotency-Key",
            "If-Match-Version",
            "bearerAuth:",
            "PHI-safe audit",
            "downloaded copies cannot be recalled",
            "operationId: enqueueUploadProcessing",
            "operationId: reviewFact",
            "operationId: createShareVersion",
            "operationId: revokeShareVersion",
        ):
            self.assertIn(marker, text)

    def test_no_real_fixture_or_credential_extensions_are_present(self) -> None:
        root = Path(__file__).parents[3]
        prohibited = {".pdf", ".dcm", ".heic"}
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in prohibited:
                self.fail(f"clinical fixture present: {path}")

    def test_freeze_adr_captures_production_boundaries_and_open_decisions(self) -> None:
        path = Path(__file__).parents[3] / "docs" / "adr" / "adr-0001-api-contract-freeze.md"
        text = path.read_text(encoding="utf-8")
        for marker in (
            "status: \"Accepted\"",
            "PostgreSQL",
            "encrypted object storage",
            "durable queue",
            "identity verification",
            "retention periods",
            "historical snapshots",
            "Revocation blocks new access",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
