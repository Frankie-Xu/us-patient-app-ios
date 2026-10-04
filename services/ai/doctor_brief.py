"""Bounded, verbatim doctor brief projection; never generates clinical advice.

Callers must derive scope from an authenticated API authorization decision.
This offline projection enforces that supplied scope; it cannot authenticate it.
Patient content belongs only in the authorized response, never diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping

from .api_projection import API_VERSION
from .doctor_view import evaluate_doctor_view
from .schema import Claim, Conflict


BRIEF_SCHEMA = "patient-app-ai/doctor-brief"
BRIEF_SCHEMA_VERSION = "1.0.0"
MAX_FACTS = 12
MAX_GOALS = 4
MAX_TASKS = 6
MAX_TEXT_CHARACTERS = 4000


class DoctorBriefBlocked(ValueError):
    """A content-free error safe for diagnostic logging."""

    def __init__(self, codes: Iterable[str]) -> None:
        self.codes = tuple(sorted(set(codes)))
        super().__init__("doctor brief blocked: " + ", ".join(self.codes))


@dataclass(frozen=True)
class DoctorBriefScope:
    owner_id: str = field(repr=False)
    visit_id: str
    authorized_claim_ids: frozenset[str]
    claim_owner_ids: Mapping[str, str] = field(default_factory=dict, repr=False)
    claim_visit_ids: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        ids = frozenset(self.authorized_claim_ids)
        if any(not isinstance(value, str) or not value.strip() for value in (self.owner_id, self.visit_id, *ids)):
            raise DoctorBriefBlocked(("doctor_brief.invalid_scope",))
        object.__setattr__(self, "authorized_claim_ids", ids)
        owners, visits = dict(self.claim_owner_ids), dict(self.claim_visit_ids)
        if any(not isinstance(key, str) or not isinstance(value, str) or not value.strip() for key, value in (*owners.items(), *visits.items())):
            raise DoctorBriefBlocked(("doctor_brief.invalid_scope",))
        object.__setattr__(self, "claim_owner_ids", owners)
        object.__setattr__(self, "claim_visit_ids", visits)


@dataclass(frozen=True)
class DoctorBriefTask:
    """A caller-supplied task with explicit user-input provenance."""

    task_id: str
    owner_id: str = field(repr=False)
    visit_id: str
    content: Claim = field(repr=False)
    status: str = "open"
    due_at: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.task_id, self.owner_id, self.visit_id)):
            raise DoctorBriefBlocked(("doctor_brief.invalid_task",))
        if not isinstance(self.content, Claim) or self.status not in {"open", "done", "cancelled"}:
            raise DoctorBriefBlocked(("doctor_brief.invalid_task",))
        if self.due_at is not None:
            try:
                parsed = datetime.fromisoformat(self.due_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
            except (AttributeError, TypeError, ValueError):
                raise DoctorBriefBlocked(("doctor_brief.invalid_task",)) from None

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "status": self.status, "due_at": self.due_at, "content": _content(self.content)}


def _content(claim: Claim) -> dict:
    return {
        "claim_id": claim.claim_id,
        "text_en": claim.text_en,
        "text_zh": claim.text_zh,
        "review_status": claim.review_status.value,
        "source_ref": claim.source_ref,
        "source_type": claim.source_type,
        "source_span": {"start": claim.source_span.start, "end": claim.source_span.end, "page": claim.source_span.page},
    }


@dataclass(frozen=True)
class DoctorBrief:
    """Authorized response content. Do not write this payload to logs/artifacts."""

    scope: DoctorBriefScope = field(repr=False)
    facts: tuple[Claim, ...] = field(repr=False)
    goals: tuple[Claim, ...] = field(repr=False)
    tasks: tuple[DoctorBriefTask, ...] = field(repr=False)

    def __post_init__(self) -> None:
        facts, goals, tasks = tuple(self.facts), tuple(self.goals), tuple(self.tasks)
        if not isinstance(self.scope, DoctorBriefScope) or not all(isinstance(item, Claim) for item in (*facts, *goals)) or not all(isinstance(item, DoctorBriefTask) for item in tasks):
            raise DoctorBriefBlocked(("doctor_brief.invalid_input",))
        claims = (*facts, *goals, *(task.content for task in tasks))
        codes = []
        if len({claim.claim_id for claim in claims}) != len(claims) or len({task.task_id for task in tasks}) != len(tasks):
            codes.append("doctor_brief.duplicate_id")
        if any(claim.claim_id not in self.scope.authorized_claim_ids for claim in claims):
            codes.append("doctor_brief.claim_out_of_scope")
        if any(claim.claim_id not in self.scope.claim_owner_ids for claim in claims):
            codes.append("doctor_brief.claim_owner_missing")
        if any(claim.claim_id not in self.scope.claim_visit_ids for claim in claims):
            codes.append("doctor_brief.claim_visit_missing")
        if any(self.scope.claim_owner_ids.get(claim.claim_id) != self.scope.owner_id for claim in claims):
            codes.append("doctor_brief.owner_mismatch")
        if any(self.scope.claim_visit_ids.get(claim.claim_id) != self.scope.visit_id for claim in claims):
            codes.append("doctor_brief.visit_mismatch")
        if any(task.owner_id != self.scope.owner_id for task in tasks):
            codes.append("doctor_brief.owner_mismatch")
        if any(task.visit_id != self.scope.visit_id for task in tasks):
            codes.append("doctor_brief.visit_mismatch")
        if any(claim.source_type != "user_input" for claim in (*goals, *(task.content for task in tasks))):
            codes.append("doctor_brief.context_not_user_input")
        if len(facts) > MAX_FACTS or len(goals) > MAX_GOALS or len(tasks) > MAX_TASKS or sum(len(claim.text_en) + len(claim.text_zh) for claim in claims) > MAX_TEXT_CHARACTERS:
            codes.append("doctor_brief.page_budget_exceeded")
        if not claims:
            codes.append("doctor_brief.empty")
        if len({claim.claim_id for claim in claims}) == len(claims):
            codes.extend(evaluate_doctor_view(claims).error_categories)
        if codes:
            raise DoctorBriefBlocked(codes)
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "goals", goals)
        object.__setattr__(self, "tasks", tasks)

    def to_dict(self) -> dict:
        return {
            "brief_schema": BRIEF_SCHEMA,
            "schema_version": BRIEF_SCHEMA_VERSION,
            "api_version": API_VERSION,
            "visit_id": self.scope.visit_id,
            "facts": [_content(claim) for claim in self.facts],
            "user_goals": [_content(claim) for claim in self.goals],
            "user_tasks": [task.to_dict() for task in self.tasks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def project_doctor_brief(
    scope: DoctorBriefScope,
    facts: Iterable[Claim],
    *,
    goals: Iterable[Claim] = (),
    tasks: Iterable[DoctorBriefTask] = (),
    conflicts: Iterable[Conflict] = (),
) -> DoctorBrief:
    """Return all selected content or reject; no rewrite, ranking or truncation.

    Supply the authoritative unresolved conflict set, including conflicts with
    claims outside the selected scope. A conflicting selected claim is blocked.
    """

    brief = DoctorBrief(scope, tuple(facts), tuple(goals), tuple(tasks))
    claims = (*brief.facts, *brief.goals, *(task.content for task in brief.tasks))
    gate = evaluate_doctor_view(claims, conflicts=conflicts)
    if gate.delivery_blocked:
        raise DoctorBriefBlocked(gate.error_categories)
    return brief
