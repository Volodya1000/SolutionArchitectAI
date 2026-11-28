from types import MappingProxyType
from uuid import UUID

from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    DecisionResult,
    RiskView,
)
from solution_architect_ai.application.models.discussion_context_models import (
    DiscussionModelContext,
)
from solution_architect_ai.application.models.discussion_input_models import (
    DiscussionInput,
    DiscussionInputAnalysis,
    DiscussionInputDecision,
    DiscussionInputEvidence,
    DiscussionInputQuestion,
    DiscussionInputRequirement,
    DiscussionInputRisk,
    DiscussionInputSource,
    DiscussionInputSubject,
    PreparedDiscussion,
)
from solution_architect_ai.application.models.extraction_models import RequirementView, SourceRef
from solution_architect_ai.application.prompts.discussion_prompt import discussion_messages


class DiscussionInputBuilder:
    def __init__(self, context: DiscussionModelContext) -> None:
        self.context: DiscussionModelContext = context
        self.source_labels: dict[tuple[UUID | None, str], str] = {
            (source.version_id, source.fragment_id): f"f{index}"
            for index, source in enumerate(context.source_fragments)
        }
        self.requirement_labels: dict[UUID, str] = {
            requirement.id: f"r{index}"
            for index, requirement in enumerate(
                context.analysis.requirements if context.analysis else []
            )
        }
        self.question_labels: dict[UUID, str] = {
            question.id: f"q{index}"
            for index, question in enumerate(context.analysis.questions if context.analysis else [])
        }
        self.decision_labels: dict[UUID, str] = {
            decision.decision_id: f"d{index}"
            for index, decision in enumerate(context.analysis.decisions if context.analysis else [])
        }
        self.references: dict[str, str] = {}

    def evidence(self, source: SourceRef) -> DiscussionInputEvidence:
        return DiscussionInputEvidence(
            fragment_id=self.source_labels.get(
                (source.version_id, source.fragment_id), "unavailable"
            ),
            quote=source.quote,
            status=source.status,
            reason=source.reason,
        )

    def sources(self) -> list[DiscussionInputSource]:
        result: list[DiscussionInputSource] = []
        source: SourceRef
        for source in self.context.source_fragments:
            label: str = self.source_labels[(source.version_id, source.fragment_id)]
            if source.version_id is not None:
                suffix: str = (
                    f"&run={self.context.subject.analysis_id}"
                    if self.context.subject.analysis_id
                    else ""
                )
                self.references[label] = (
                    f"/documents?version={source.version_id}&fragment={source.fragment_id}{suffix}"
                )
            result.append(
                DiscussionInputSource(
                    **self.evidence(source).model_dump(),
                    location=f"{source.locator.kind}:{source.locator.start}-{source.locator.end}"
                    if source.locator
                    else "",
                )
            )
        return result

    def requirement(self, requirement: RequirementView) -> DiscussionInputRequirement:
        label: str = self.requirement_labels[requirement.id]
        self.references[label] = (
            f"/requirements?run={self.context.subject.analysis_id}&requirement={requirement.id}"
        )
        return DiscussionInputRequirement(
            id=label,
            category=requirement.category,
            original_text=requirement.original_text,
            normalized_text=requirement.normalized_text,
            sources=[self.evidence(source) for source in requirement.sources],
        )

    def question(self, question: ClarificationQuestion) -> DiscussionInputQuestion:
        label: str = self.question_labels[question.id]
        self.references[label] = (
            f"/requirements?run={self.context.subject.analysis_id}&tab=clarifications#question-{question.id}"
        )
        return DiscussionInputQuestion(
            id=label,
            text=question.text,
            revision=question.revision,
            basis=question.basis,
            dependent_decision=question.dependent_decision,
            blocking=question.blocks_completion,
            status=question.status,
            mandatory_conflict=question.mandatory_conflict,
            requirement_ids=[
                self.requirement_labels[identifier]
                for identifier in question.requirement_ids
                if identifier in self.requirement_labels
            ],
            sources=[self.evidence(source) for source in question.sources],
        )

    def decision(self, decision: DecisionResult) -> DiscussionInputDecision:
        question: ClarificationQuestion | None = (
            next(
                (
                    item
                    for item in self.context.analysis.questions
                    if item.id == decision.question_id
                ),
                None,
            )
            if self.context.analysis is not None
            else None
        )
        applies: bool = (
            question is not None
            and question.revision == decision.question_revision
            and decision.resolution != "rejected"
        )
        identifiers: list[UUID] = (
            question.requirement_ids
            if applies and question is not None
            else decision.requirement_ids
        )
        label: str = self.decision_labels[decision.decision_id]
        self.references[label] = (
            f"/requirements?run={self.context.subject.analysis_id}&tab=clarifications#decision-{decision.decision_id}"
        )
        return DiscussionInputDecision(
            id=label,
            question_id=self.question_labels.get(decision.question_id, "historical_question"),
            revision=decision.revision,
            question_revision=decision.question_revision,
            applies_to_current_question=applies,
            analysis="a0"
            if decision.run_id == self.context.subject.analysis_id
            else "previous_analysis",
            requirement_ids=[
                self.requirement_labels[identifier]
                for identifier in identifiers
                if identifier in self.requirement_labels
            ],
            kind=decision.kind,
            text=decision.text,
            basis=decision.basis,
            author=decision.author,
            created_at=decision.created_at,
            assumption=decision.assumption,
            resolution=decision.resolution,
            resolution_reason=decision.resolution_reason,
        )

    def risk(self, risk: RiskView, index: int) -> DiscussionInputRisk:
        label: str = f"k{index}"
        self.references[label] = (
            f"/requirements?run={self.context.subject.analysis_id}&tab=risks#risk-{risk.id}"
        )
        return DiscussionInputRisk(
            id=label,
            decision_id=self.decision_labels.get(risk.decision_id, "historical_decision"),
            consequences=risk.consequences,
            mitigation=risk.mitigation,
            status=risk.status,
            resolution_reason=risk.resolution_reason,
        )

    def analysis(self) -> DiscussionInputAnalysis | None:
        if self.context.analysis is None:
            return None
        return DiscussionInputAnalysis(
            id="a0",
            requirements=[self.requirement(item) for item in self.context.analysis.requirements],
            questions=[self.question(item) for item in self.context.analysis.questions],
            decisions=[self.decision(item) for item in self.context.analysis.decisions],
            risks=[
                self.risk(item, index) for index, item in enumerate(self.context.analysis.risks)
            ],
        )

    def prepare(self) -> PreparedDiscussion:
        payload: DiscussionInput = DiscussionInput(
            subject=DiscussionInputSubject(
                kind=self.context.subject.kind,
                title=self.context.subject.title,
                requirement_id=self.requirement_labels.get(self.context.subject.requirement_id)
                if self.context.subject.requirement_id
                else None,
                fragment_id=self.source_labels.get(
                    (self.context.subject.version_id, str(self.context.subject.fragment_id))
                )
                if self.context.subject.fragment_id
                else None,
            ),
            candidate_sources=[self.evidence(source) for source in self.context.candidate_sources],
            source_fragments=self.sources(),
            analysis=self.analysis(),
            omitted_fragment_count=self.context.context_manifest.omitted_fragment_count,
            omission_reason=self.context.context_manifest.omission_reason,
        )
        return PreparedDiscussion(discussion_messages(payload), MappingProxyType(self.references))
