"""Provider-neutral, deterministic PDF export for reviewed record snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping
from unicodedata import normalize

from .models import Document, DocumentStatus, Fact, ReviewStatus


class PdfExportError(ValueError):
    """Stable, content-free export failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(detail)


class PdfExportBlocked(PdfExportError):
    """Export is intentionally fail-closed for unsafe or stale content."""


@dataclass(frozen=True)
class PdfExportArtifact:
    document_id: str
    document_version: int
    content: bytes
    content_type: str = "application/pdf"

    @property
    def sha256(self) -> str:
        return sha256(self.content).hexdigest()


def _safe_ascii(value: Any) -> str:
    text = normalize("NFKD", str(value)).encode("ascii", "replace").decode("ascii")
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def _pdf_escape(value: str) -> bytes:
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("latin-1", "replace")
    )


def _wrapped_lines(value: str, width: int = 96) -> list[str]:
    text = _safe_ascii(value)
    if not text:
        return [""]
    return [text[index : index + width] for index in range(0, len(text), width)]


def _build_pdf(lines: Iterable[str]) -> bytes:
    """Build a one-page PDF without timestamps, random IDs, or external state."""
    normalized = [line for raw in lines for line in _wrapped_lines(raw)]
    if not normalized:
        normalized = [""]
    commands = [b"BT", b"/F1 10 Tf", b"72 760 Td"]
    for index, line in enumerate(normalized[:42]):
        if index:
            commands.append(b"0 -16 Td")
        commands.append(b"(" + _pdf_escape(line) + b") Tj")
    commands.append(b"ET")
    stream = b"\n".join(commands) + b"\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"endstream",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _brief_is_blocked(doctor_brief: Mapping[str, Any]) -> bool:
    for key in ("conflicts", "unresolved_conflicts", "conflict_ids"):
        value = doctor_brief.get(key)
        if value:
            return True
    count = doctor_brief.get("conflict_count", 0)
    if isinstance(count, bool) or (isinstance(count, (int, float)) and count > 0):
        return True
    for key in ("facts", "goals", "user_goals", "tasks", "user_tasks"):
        values = doctor_brief.get(key, ())
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if not isinstance(value, Mapping):
                return True
            nested = value.get("content")
            if isinstance(nested, Mapping):
                value = nested
            status = value.get("review_status")
            if status is not None and status != ReviewStatus.CONFIRMED.value:
                return True
    return False


class PdfExporter:
    """Validate and render an immutable, reviewed document projection."""

    def render(
        self,
        document: Document,
        facts: Iterable[Fact] = (),
        *,
        document_version: int | None = None,
        fact_ids: Iterable[str] | None = None,
        doctor_brief: Mapping[str, Any] | None = None,
    ) -> PdfExportArtifact:
        requested_version = document.version if document_version is None else document_version
        if requested_version != document.version:
            raise PdfExportBlocked(
                "DOCUMENT_VERSION_MISMATCH",
                "requested document version is not the current immutable version",
            )
        if document.status != DocumentStatus.READY:
            raise PdfExportBlocked("DOCUMENT_NOT_READY", "document is not ready for export")
        selected = tuple(facts)
        if fact_ids is not None:
            requested_ids = tuple(str(item) for item in fact_ids)
            by_id = {fact.id: fact for fact in selected}
            if len(by_id) != len(selected) or any(item not in by_id for item in requested_ids):
                raise PdfExportBlocked("FACT_SELECTION_INVALID", "requested facts are unavailable")
            selected = tuple(by_id[item] for item in requested_ids)
        if any(fact.document_id != document.id for fact in selected):
            raise PdfExportBlocked("FACT_SELECTION_INVALID", "fact is outside the document")
        if any(fact.review_status != ReviewStatus.CONFIRMED for fact in selected):
            raise PdfExportBlocked("UNREVIEWED_CONTENT", "all exported facts must be confirmed")
        by_label: dict[str, set[str]] = {}
        for fact in selected:
            by_label.setdefault(fact.label.strip().casefold(), set()).add(fact.value.strip().casefold())
        if any(len(values) > 1 for values in by_label.values()):
            raise PdfExportBlocked("CONFLICTED_CONTENT", "conflicting facts cannot be exported")
        if doctor_brief is not None:
            if not isinstance(doctor_brief, Mapping):
                raise PdfExportBlocked("INVALID_DOCTOR_BRIEF", "doctor brief is invalid")
            if _brief_is_blocked(doctor_brief):
                raise PdfExportBlocked(
                    "CONFLICTED_CONTENT",
                    "doctor brief contains unresolved or unreviewed content",
                )
        lines = [
            "US Patient App record export",
            f"Document: {document.filename}",
            f"Document version: {document.version}",
            f"Document checksum: {document.sha256}",
        ]
        for fact in selected:
            lines.append(f"Fact: {fact.label} = {fact.value} [{fact.source_ref}]")
        if doctor_brief is not None:
            lines.append("Doctor brief:")
            lines.extend(json.dumps(doctor_brief, ensure_ascii=False, sort_keys=True).splitlines())
        return PdfExportArtifact(document.id, document.version, _build_pdf(lines))


def render_pdf(
    document: Document,
    facts: Iterable[Fact] = (),
    *,
    document_version: int | None = None,
    fact_ids: Iterable[str] | None = None,
    doctor_brief: Mapping[str, Any] | None = None,
) -> PdfExportArtifact:
    return PdfExporter().render(
        document,
        facts,
        document_version=document_version,
        fact_ids=fact_ids,
        doctor_brief=doctor_brief,
    )
