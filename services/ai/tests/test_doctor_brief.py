import json
import unittest
from dataclasses import replace

from services.ai.doctor_brief import (
    DoctorBriefBlocked,
    DoctorBriefScope,
    DoctorBriefTask,
    project_doctor_brief,
)
from services.ai.schema import Claim, Conflict, ReviewStatus, Severity, SourceSpan


class DoctorBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fact = Claim(
            claim_id="fact-1", text_en="Medication list supplied", text_zh="已提供用药清单",
            source_ref="doc-1", source_type="uploaded_document", source_span=SourceSpan(0, 8),
            confidence=1, review_status=ReviewStatus.CONFIRMED,
        )
        self.goal = Claim(
            claim_id="goal-1", text_en="Discuss current symptoms", text_zh="讨论当前症状",
            source_ref="input-1", source_type="user_input", source_span=SourceSpan(0, 8),
            confidence=1, review_status=ReviewStatus.CONFIRMED,
        )
        self.task_content = Claim(
            claim_id="task-claim-1", text_en="Bring the medication list", text_zh="携带用药清单",
            source_ref="input-2", source_type="user_input", source_span=SourceSpan(0, 8),
            confidence=1, review_status=ReviewStatus.CONFIRMED,
        )
        self.scope = DoctorBriefScope(
            owner_id="patient-1", visit_id="visit-1",
            authorized_claim_ids=frozenset({"fact-1", "goal-1", "task-claim-1"}),
            claim_owner_ids={"fact-1": "patient-1", "goal-1": "patient-1", "task-claim-1": "patient-1"},
            claim_visit_ids={"fact-1": "visit-1", "goal-1": "visit-1", "task-claim-1": "visit-1"},
        )

    def test_projects_verbatim_fact_goal_and_task_with_provenance(self) -> None:
        task = DoctorBriefTask("task-1", "patient-1", "visit-1", self.task_content, due_at="2026-10-05T09:00:00+00:00")
        brief = project_doctor_brief(self.scope, (self.fact,), goals=(self.goal,), tasks=(task,))
        payload = brief.to_dict()
        self.assertEqual(payload["facts"][0]["text_en"], self.fact.text_en)
        self.assertEqual(payload["user_goals"][0]["source_ref"], "input-1")
        self.assertEqual(payload["user_tasks"][0]["content"]["claim_id"], "task-claim-1")
        self.assertNotIn("diagnosis", json.dumps(payload).lower())
        self.assertNotIn("recommendation", json.dumps(payload).lower())

    def test_unconfirmed_fact_is_blocked(self) -> None:
        with self.assertRaises(DoctorBriefBlocked) as caught:
            project_doctor_brief(self.scope, (replace(self.fact, review_status=ReviewStatus.NEEDS_REVIEW),))
        self.assertIn("doctor_view.not_confirmed", caught.exception.codes)

    def test_missing_provenance_is_blocked(self) -> None:
        with self.assertRaises(DoctorBriefBlocked) as caught:
            project_doctor_brief(self.scope, (replace(self.fact, source_span=None),))
        self.assertIn("doctor_view.source_span_missing", caught.exception.codes)

    def test_conflict_is_blocked(self) -> None:
        conflict = Conflict("conflict-1", ("fact-1", "other"), Severity.HIGH)
        with self.assertRaises(DoctorBriefBlocked) as caught:
            project_doctor_brief(self.scope, (self.fact,), conflicts=(conflict,))
        self.assertIn("doctor_view.conflict_unresolved", caught.exception.codes)

    def test_scope_owner_and_visit_boundaries_are_blocked(self) -> None:
        owner_scope = replace(self.scope, claim_owner_ids={**self.scope.claim_owner_ids, "fact-1": "other"})
        with self.assertRaises(DoctorBriefBlocked) as owner_error:
            project_doctor_brief(owner_scope, (self.fact,))
        self.assertIn("doctor_brief.owner_mismatch", owner_error.exception.codes)
        visit_scope = replace(self.scope, claim_visit_ids={**self.scope.claim_visit_ids, "fact-1": "other-visit"})
        with self.assertRaises(DoctorBriefBlocked) as visit_error:
            project_doctor_brief(visit_scope, (self.fact,))
        self.assertIn("doctor_brief.visit_mismatch", visit_error.exception.codes)

    def test_task_owner_and_visit_boundaries_are_blocked(self) -> None:
        task = DoctorBriefTask("task-1", "other", "visit-1", self.task_content)
        with self.assertRaises(DoctorBriefBlocked) as caught:
            project_doctor_brief(self.scope, (self.fact,), tasks=(task,))
        self.assertIn("doctor_brief.owner_mismatch", caught.exception.codes)

    def test_out_of_scope_and_budget_are_rejected_without_truncation(self) -> None:
        with self.assertRaises(DoctorBriefBlocked) as scope_error:
            project_doctor_brief(replace(self.scope, authorized_claim_ids=frozenset({"fact-1"})), (self.fact,), goals=(self.goal,))
        self.assertIn("doctor_brief.claim_out_of_scope", scope_error.exception.codes)
        extra = tuple(replace(self.fact, claim_id=f"fact-{index}") for index in range(13))
        oversized_scope = replace(self.scope, authorized_claim_ids=frozenset(claim.claim_id for claim in extra), claim_owner_ids={claim.claim_id: "patient-1" for claim in extra}, claim_visit_ids={claim.claim_id: "visit-1" for claim in extra})
        with self.assertRaises(DoctorBriefBlocked) as budget_error:
            project_doctor_brief(oversized_scope, extra)
        self.assertIn("doctor_brief.page_budget_exceeded", budget_error.exception.codes)


if __name__ == "__main__":
    unittest.main()
