import json
from typing import Annotated
from uuid import UUID

from pydantic import Field, TypeAdapter
from sqlalchemy import Result, ScalarResult, Select, and_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.context.mandatory_conflict_questions import (
    bind_confirmed_conflicts,
)
from solution_architect_ai.application.context.source_fingerprints import (
    has_changed_clarification_basis,
    requirement_basis_fingerprint,
)
from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.errors.clarification_errors import PermissionDenied
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    ClarificationMetadata,
    ClarificationQuestion,
    ClarificationView,
    CompletedCycle,
    DecisionResult,
    QuestionStatus,
    RiskView,
)
from solution_architect_ai.application.models.conflict_assessment_models import ConflictAssessment
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
    RequirementView,
    SourceRef,
)
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationRunRow,
    DecisionRow,
    QuestionLinkRow,
    QuestionRevisionRow,
    QuestionRow,
    RiskRow,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.stored_data import (
    read_stored_json,
    read_stored_json_value,
    read_stored_value,
)


class ClarificationQueries:
    def __init__(self, session: AsyncSession, actor: ActorContext) -> None:
        self.session: AsyncSession = session
        self.actor: ActorContext = actor

    async def extraction(self, run_id: UUID, *, lock: bool = False) -> ExtractionRow:
        query: Select[ExtractionRow] = select(ExtractionRow).where(
            ExtractionRow.id == run_id, ExtractionRow.task_id == self.actor.task_id
        )
        row: ExtractionRow | None = await self.session.scalar(
            query.with_for_update() if lock else query
        )
        if row is None:
            raise Missing("extraction")
        return row

    async def run(self, run_id: UUID, *, lock: bool = False) -> ClarificationRunRow:
        extraction: ExtractionRow = await self.extraction(run_id, lock=lock)
        row: ClarificationRunRow | None = await self.session.get(
            ClarificationRunRow, run_id, with_for_update=lock
        )
        if row is None:
            await self.extraction(run_id, lock=True)
            row = await self.session.get(ClarificationRunRow, run_id, populate_existing=True)
        if row is None:
            history_id: UUID = await self.resolve_history(extraction)
            row = ClarificationRunRow(
                run_id=run_id,
                history_id=history_id,
                active_seconds=read_stored_json(
                    ExtractionView,
                    extraction.snapshot_json,
                    failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
                ).elapsed_seconds,
            )
            self.session.add(row)
            await self.session.flush()
        return row

    async def resolve_history(self, extraction: ExtractionRow) -> UUID:
        command: ExtractionStart = read_stored_json(
            ExtractionStart,
            extraction.command_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if command.answer_history_mode == "new":
            return extraction.id
        if command.answer_history_id is None or command.answer_history_id == self.actor.task_id:
            return self.actor.task_id
        owner: ClarificationRunRow | None = await self.session.scalar(
            select(ClarificationRunRow)
            .join(ExtractionRow)
            .where(
                ClarificationRunRow.history_id == command.answer_history_id,
                ExtractionRow.task_id == self.actor.task_id,
            )
            .limit(1)
        )
        if owner is None:
            raise Missing("answer_history")
        return command.answer_history_id

    async def links(self, run_id: UUID) -> list[QuestionLinkRow]:
        return list(
            (
                await self.session.scalars(
                    select(QuestionLinkRow).where(QuestionLinkRow.run_id == run_id)
                )
            ).all()
        )

    async def set_review_metadata(self, run_id: UUID, metadata: ClarificationMetadata) -> None:
        state: ClarificationRunRow = await self.run(run_id, lock=True)
        state.metadata_json = metadata.model_dump_json()

    async def question(
        self, run_id: UUID, question_id: UUID, *, lock: bool = False
    ) -> QuestionRevisionRow:
        await self.extraction(run_id)
        link: QuestionLinkRow | None = await self.session.get(
            QuestionLinkRow, (run_id, question_id)
        )
        if link is None:
            raise Missing("question")
        query: Select[QuestionRevisionRow] = select(QuestionRevisionRow).where(
            QuestionRevisionRow.question_id == question_id,
            QuestionRevisionRow.revision == link.revision,
        )
        row: QuestionRevisionRow | None = await self.session.scalar(
            query.with_for_update() if lock else query
        )
        if row is None:
            raise Missing("question_revision")
        return row

    async def get(self, run_id: UUID) -> ClarificationView:
        extraction: ExtractionRow = await self.extraction(run_id)
        state: ClarificationRunRow = await self.run(run_id)
        view: ClarificationView = ClarificationView(
            run_id=run_id,
            history_id=state.history_id,
            cycle=state.cycle,
            initialized=state.initialized,
            resume_pending=state.resume_pending,
            resume_version=state.resume_version,
            metadata=read_stored_json(
                ClarificationMetadata,
                state.metadata_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            if state.metadata_json is not None
            else None,
            completed_cycles=read_stored_json_value(
                TypeAdapter(list[CompletedCycle]),
                state.completed_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            ),
            conflict_assessments=read_stored_json_value(
                TypeAdapter(list[ConflictAssessment]),
                state.assessments_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            ),
            requirements=read_stored_json(
                ExtractionView,
                extraction.snapshot_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            ).requirements,
        )
        links: list[QuestionLinkRow] = await self.links(run_id)
        revisions: dict[tuple[UUID, int], QuestionRevisionRow] = await self._read_revisions(links)
        decisions: dict[UUID, list[tuple[DecisionRow, RiskRow | None]]] = (
            await self._read_decisions(run_id) if links else {}
        )
        link: QuestionLinkRow
        for link in links:
            question: ClarificationQuestion = self._question_view(
                link, revisions.get((link.question_id, link.revision))
            )
            view.questions.append(question)
            decision: DecisionRow
            risk: RiskRow | None
            for decision, risk in decisions.get(question.id, []):
                item: DecisionResult = read_stored_json(
                    DecisionResult,
                    decision.snapshot_json,
                    failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
                )
                view.decisions.append(item)
                if risk is not None:
                    view.risks.append(
                        read_stored_json(
                            RiskView,
                            risk.snapshot_json,
                            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
                        )
                    )
        self.apply_decisions(view)
        return view

    @staticmethod
    def _question_view(
        link: QuestionLinkRow,
        revision: QuestionRevisionRow | None,
    ) -> ClarificationQuestion:
        if revision is None:
            raise Missing("question_revision")
        question: ClarificationQuestion = read_stored_json(
            ClarificationQuestion,
            revision.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        question.requirement_ids = read_stored_json_value(
            TypeAdapter(Annotated[list[UUID], Field(min_length=1)]),
            link.requirement_ids_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if link.sources_json is not None:
            question.sources = read_stored_json_value(
                TypeAdapter(list[SourceRef]),
                link.sources_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
        return question

    async def _read_revisions(
        self, links: list[QuestionLinkRow]
    ) -> dict[tuple[UUID, int], QuestionRevisionRow]:
        if not links:
            return {}
        revisions: ScalarResult[QuestionRevisionRow] = await self.session.scalars(
            select(QuestionRevisionRow).where(
                tuple_(QuestionRevisionRow.question_id, QuestionRevisionRow.revision).in_(
                    [(link.question_id, link.revision) for link in links]
                )
            )
        )
        return {(revision.question_id, revision.revision): revision for revision in revisions}

    async def _read_decisions(
        self, run_id: UUID
    ) -> dict[UUID, list[tuple[DecisionRow, RiskRow | None]]]:
        rows: Result[DecisionRow, RiskRow | None] = await self.session.execute(
            select(DecisionRow, RiskRow)
            .join(
                QuestionLinkRow,
                and_(
                    QuestionLinkRow.question_id == DecisionRow.question_id,
                    DecisionRow.question_revision <= QuestionLinkRow.revision,
                ),
            )
            .outerjoin(RiskRow, RiskRow.decision_id == DecisionRow.id)
            .where(QuestionLinkRow.run_id == run_id)
            .order_by(DecisionRow.question_revision)
        )
        decisions: dict[UUID, list[tuple[DecisionRow, RiskRow | None]]] = {}
        decision: DecisionRow
        risk: RiskRow | None
        for decision, risk in rows:
            decisions.setdefault(decision.question_id, []).append((decision, risk))
        return decisions

    @staticmethod
    def apply_decisions(view: ClarificationView) -> None:
        revisions: dict[UUID, int] = {question.id: question.revision for question in view.questions}
        requirement_ids: dict[UUID, list[UUID]] = {
            question.id: question.requirement_ids for question in view.questions
        }
        requirement: RequirementView
        for requirement in view.requirements:
            additions: list[str] = [
                decision.text
                for decision in view.decisions
                if requirement.id in requirement_ids.get(decision.question_id, [])
                and decision.resolution != "rejected"
                and decision.question_revision == revisions.get(decision.question_id)
            ]
            if additions:
                requirement.normalized_text += "\n" + "\n".join(additions)

    async def save_questions(
        self,
        run_id: UUID,
        questions: list[ClarificationQuestion],
        metadata: ClarificationMetadata | None = None,
    ) -> None:
        state: ClarificationRunRow = await self.run(run_id, lock=True)
        if state.initialized:
            return
        extraction: ExtractionRow = await self.extraction(run_id)
        requirements: list[RequirementView] = read_stored_json(
            ExtractionView,
            extraction.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        ).requirements
        assessments: list[ConflictAssessment] = read_stored_json_value(
            TypeAdapter(list[ConflictAssessment]),
            state.assessments_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        questions = bind_confirmed_conflicts(requirements, questions, assessments)
        question: ClarificationQuestion
        for question in questions:
            await self.save_question(state, question)
        state.initialized = True
        state.metadata_json = metadata.model_dump_json() if metadata is not None else None

    async def save_question(
        self, state: ClarificationRunRow, question: ClarificationQuestion
    ) -> None:
        extraction: ExtractionRow = await self.extraction(state.run_id)
        snapshot: ExtractionView = read_stored_json(
            ExtractionView,
            extraction.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        question.requirement_basis_fingerprints = {
            requirement.id: requirement_basis_fingerprint(requirement)
            for requirement in snapshot.requirements
            if requirement.id in question.requirement_ids
        }
        identity: QuestionRow | None = await self.session.scalar(
            select(QuestionRow)
            .where(
                QuestionRow.task_id == self.actor.task_id,
                QuestionRow.history_id == state.history_id,
                QuestionRow.gap_key == question.gap_key,
            )
            .with_for_update()
        )
        if identity is None:
            identity = QuestionRow(
                id=question.id,
                task_id=self.actor.task_id,
                history_id=state.history_id,
                gap_key=question.gap_key,
                revision=1,
            )
            self.session.add(identity)
            await self.session.flush()
            self.session.add(
                QuestionRevisionRow(
                    question_id=identity.id,
                    revision=1,
                    status="open",
                    snapshot_json=question.model_dump_json(),
                )
            )
        else:
            current_revision: QuestionRevisionRow = await self.question_revision(
                identity.id, identity.revision
            )
            current_question: ClarificationQuestion = read_stored_json(
                ClarificationQuestion,
                current_revision.snapshot_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            if has_changed_clarification_basis(current_question, question):
                question.previous_basis = current_question.basis
                question.previous_sources = current_question.sources
                await self.revise_question(identity, question)
        link: QuestionLinkRow | None = await self.session.get(
            QuestionLinkRow, (state.run_id, identity.id)
        )
        if link is None:
            self.session.add(
                QuestionLinkRow(
                    run_id=state.run_id,
                    question_id=identity.id,
                    revision=identity.revision,
                    requirement_ids_json=json.dumps(
                        [str(identifier) for identifier in question.requirement_ids]
                    ),
                    sources_json=TypeAdapter(list[SourceRef]).dump_json(question.sources).decode(),
                )
            )
        await self.session.flush()

    async def bound_question(self, run_id: UUID, question_id: UUID) -> ClarificationQuestion:
        revision: QuestionRevisionRow = await self.question(run_id, question_id)
        question: ClarificationQuestion = read_stored_json(
            ClarificationQuestion,
            revision.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        link: QuestionLinkRow | None = await self.session.get(
            QuestionLinkRow, (run_id, question_id)
        )
        if link is None:
            raise Missing("question")
        question.requirement_ids = read_stored_json_value(
            TypeAdapter(Annotated[list[UUID], Field(min_length=1)]),
            link.requirement_ids_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if link.sources_json is not None:
            question.sources = read_stored_json_value(
                TypeAdapter(list[SourceRef]),
                link.sources_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
        return question

    async def question_revision(self, question_id: UUID, revision: int) -> QuestionRevisionRow:
        row: QuestionRevisionRow | None = await self.session.get(
            QuestionRevisionRow, (question_id, revision)
        )
        if row is None:
            raise Missing("question_revision")
        return row

    async def revise_question(self, identity: QuestionRow, question: ClarificationQuestion) -> None:
        previous: QuestionRevisionRow | None = await self.session.get(
            QuestionRevisionRow, (identity.id, identity.revision)
        )
        if previous is None:
            raise Missing("question_revision")
        old: ClarificationQuestion = read_stored_json(
            ClarificationQuestion,
            previous.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if question.previous_basis != old.basis:
            return
        if not has_changed_clarification_basis(old, question):
            return
        identity.revision += 1
        question.id, question.revision, question.status = identity.id, identity.revision, "open"
        self.session.add(
            QuestionRevisionRow(
                question_id=identity.id,
                revision=identity.revision,
                status="open",
                snapshot_json=question.model_dump_json(),
            )
        )

    async def history(self, run_id: UUID) -> list[ClarificationQuestion]:
        state: ClarificationRunRow = await self.run(run_id)
        rows: ScalarResult[QuestionRevisionRow] = await self.session.scalars(
            select(QuestionRevisionRow)
            .join(QuestionRow)
            .where(
                QuestionRow.task_id == self.actor.task_id,
                QuestionRow.history_id == state.history_id,
                QuestionRevisionRow.revision == QuestionRow.revision,
            )
        )
        questions: list[ClarificationQuestion] = []
        row: QuestionRevisionRow
        for row in rows:
            question: ClarificationQuestion = read_stored_json(
                ClarificationQuestion,
                row.snapshot_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            question.status = read_stored_value(
                TypeAdapter(QuestionStatus),
                row.status,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
                strict=True,
            )
            questions.append(question)
        return questions

    def require_writer(self) -> None:
        if not self.actor.can_write:
            raise PermissionDenied("permission_denied")

    async def history_decisions(self, run_id: UUID) -> list[DecisionResult]:
        state: ClarificationRunRow = await self.run(run_id)
        rows: ScalarResult[DecisionRow] = await self.session.scalars(
            select(DecisionRow)
            .join(QuestionRow)
            .where(
                QuestionRow.task_id == self.actor.task_id,
                QuestionRow.history_id == state.history_id,
            )
        )
        return [
            read_stored_json(
                DecisionResult,
                row.snapshot_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            for row in rows
        ]
