import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Select, and_, or_, select, text

from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.errors.clarification_errors import (
    ClarificationConflict as Conflict,
)
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationQuestion,
    ClarificationView,
    CommandResult,
    DecisionResult,
    ResolveAssumption,
    ResumeRun,
    RiskView,
    SourceVersion,
)
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
)
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationOperationRow,
    ClarificationRunRow,
    DecisionRow,
    QuestionLinkRow,
    QuestionRevisionRow,
    QuestionRow,
    RiskRow,
)
from solution_architect_ai.persistence.clarifications.clarification_queries import (
    ClarificationQueries,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow


class ClarificationCommands:
    def __init__(self, queries: ClarificationQueries) -> None:
        self.queries: ClarificationQueries = queries

    async def replay(
        self, operation_id: UUID, kind: str, target: UUID, command: BaseModel
    ) -> str | None:
        self.queries.require_writer()
        digest: str = self.digest(kind, target, command)
        await self.queries.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"{self.queries.actor.task_id}:{operation_id}"},
        )
        row: ClarificationOperationRow | None = await self.queries.session.get(
            ClarificationOperationRow, (self.queries.actor.task_id, operation_id)
        )
        if row is not None:
            if row.digest != digest:
                raise Conflict("operation_payload_changed")
            return row.result_json
        return None

    @staticmethod
    def digest(kind: str, target: UUID, command: BaseModel) -> str:
        return sha256(
            json.dumps(
                {"kind": kind, "target": str(target), "command": command.model_dump(mode="json")},
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def record(
        self, kind: str, target: UUID, command: BaseModel, result: DecisionResult | CommandResult
    ) -> None:
        self.queries.session.add(
            ClarificationOperationRow(
                task_id=self.queries.actor.task_id,
                operation_id=result.operation_id,
                digest=self.digest(kind, target, command),
                kind=kind,
                result_json=result.model_dump_json(),
            )
        )

    async def answer(
        self, run_id: UUID, question_id: UUID, command: AnswerClarification
    ) -> DecisionResult:
        await self.queries.extraction(run_id)
        operation_kind: str = f"answer:{run_id}"
        previous: str | None = await self.replay(
            command.operation_id, operation_kind, question_id, command
        )
        if previous is not None:
            return DecisionResult.model_validate_json(previous)
        state: ClarificationRunRow = await self.queries.run(run_id, lock=True)
        revision: QuestionRevisionRow = await self.queries.question(run_id, question_id, lock=True)
        if revision.revision != command.expected_question_revision or revision.status != "open":
            raise Conflict("stale_question_revision")
        extraction: ExtractionRow = await self.queries.extraction(run_id)
        if extraction.status in {RunStatus.CANCELLED, RunStatus.CANCELLING, RunStatus.FAILED}:
            raise Conflict("extraction_not_resumable")
        question: ClarificationQuestion = ClarificationQuestion.model_validate_json(
            revision.snapshot_json
        )
        bound_question: ClarificationQuestion = await self.queries.bound_question(
            run_id, question_id
        )
        self.check_sources(bound_question, command.source_versions)
        decision: DecisionResult = DecisionResult(
            operation_id=command.operation_id,
            run_id=run_id,
            question_id=question_id,
            question_revision=revision.revision,
            decision_id=uuid4(),
            kind=command.kind,
            text=command.text,
            basis=command.basis,
            author_id=self.queries.actor.id,
            author=self.queries.actor.name,
            created_at=datetime.now(UTC),
            requirement_ids=bound_question.requirement_ids,
            source_versions=command.source_versions,
            assumption=command.assumption,
            risk_id=uuid4() if command.assumption is not None else None,
        )
        self.queries.session.add(
            DecisionRow(
                id=decision.decision_id,
                question_id=question_id,
                question_revision=revision.revision,
                run_id=run_id,
                snapshot_json=decision.model_dump_json(),
            )
        )
        await self.queries.session.flush()
        self.save_risk(decision)
        question.status = "assumed" if command.kind == "assumption" else "answered"
        revision.status, revision.snapshot_json = question.status, question.model_dump_json()
        state.resume_pending = True
        state.resume_version += 1
        self.record(operation_kind, question_id, command, decision)
        return decision

    async def preflight_answer(
        self, run_id: UUID, question_id: UUID, command: AnswerClarification
    ) -> DecisionResult | None:
        extraction: ExtractionRow = await self.queries.extraction(run_id)
        previous: str | None = await self.replay(
            command.operation_id, f"answer:{run_id}", question_id, command
        )
        if previous is not None:
            return DecisionResult.model_validate_json(previous)
        revision: QuestionRevisionRow = await self.queries.question(run_id, question_id)
        if revision.revision != command.expected_question_revision or revision.status != "open":
            raise Conflict("stale_question_revision")
        question: ClarificationQuestion = await self.queries.bound_question(run_id, question_id)
        self.check_sources(question, command.source_versions)
        selected: ExtractionStart = ExtractionStart.model_validate_json(extraction.command_json)
        if not {source.version_id for source in command.source_versions} <= set(
            selected.version_ids
        ):
            raise Conflict("source_versions_changed")
        return None

    async def preflight_resume(self, run_id: UUID, command: ResumeRun) -> CommandResult | None:
        await self.queries.extraction(run_id)
        previous: str | None = await self.replay(command.operation_id, "resume", run_id, command)
        return CommandResult.model_validate_json(previous) if previous is not None else None

    @staticmethod
    def check_sources(question: ClarificationQuestion, sources: list[SourceVersion]) -> None:
        expected: set[tuple[UUID | None, str | None]] = {
            (source.version_id, source.sha256) for source in question.sources
        }
        if {(source.version_id, source.sha256) for source in sources} != expected:
            raise Conflict("source_versions_changed")

    def save_risk(self, decision: DecisionResult) -> None:
        if decision.assumption is not None and decision.risk_id is not None:
            risk: RiskView = RiskView(
                id=decision.risk_id,
                decision_id=decision.decision_id,
                consequences=decision.assumption.consequences,
                mitigation=decision.assumption.mitigation,
            )
            self.queries.session.add(
                RiskRow(
                    id=risk.id,
                    decision_id=decision.decision_id,
                    snapshot_json=risk.model_dump_json(),
                )
            )

    async def resume(self, run_id: UUID, command: ResumeRun) -> CommandResult:
        await self.queries.extraction(run_id)
        previous: str | None = await self.replay(command.operation_id, "resume", run_id, command)
        if previous is not None:
            return CommandResult.model_validate_json(previous)
        state: ClarificationRunRow = await self.queries.run(run_id, lock=True)
        view: ClarificationView = await self.queries.get(run_id)
        if any(question.blocking and question.status == "open" for question in view.questions):
            raise Conflict("blocking_questions_open")
        if command.question_revisions != {
            question.id: question.revision for question in view.questions
        }:
            raise Conflict("stale_question_revision")
        expected: set[tuple[UUID | None, str | None]] = {
            (source.version_id, source.sha256)
            for question in view.questions
            for source in question.sources
        }
        if expected != {(source.version_id, source.sha256) for source in command.source_versions}:
            raise Conflict("source_versions_changed")
        extraction: ExtractionRow = await self.queries.extraction(run_id)
        if extraction.status in {RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.CANCELLING}:
            raise Conflict("extraction_not_resumable")
        state.resume_pending = True
        state.resume_version += 1
        result: CommandResult = CommandResult(
            operation_id=command.operation_id, run_id=run_id, cycle=state.cycle
        )
        self.record("resume", run_id, command, result)
        return result

    async def resolve(self, decision_id: UUID, command: ResolveAssumption) -> DecisionResult:
        decision_row: DecisionRow | None = await self.queries.session.get(DecisionRow, decision_id)
        if decision_row is None:
            raise Missing("assumption")
        await self.queries.extraction(decision_row.run_id)
        previous: str | None = await self.replay(
            command.operation_id, "resolve", decision_id, command
        )
        if previous is not None:
            return DecisionResult.model_validate_json(previous)
        extractions: list[ExtractionRow] = await self._lock_resolution_runs(decision_row)
        await self.queries.run(decision_row.run_id, lock=True)
        await self.queries.session.refresh(decision_row, with_for_update=True)
        decision: DecisionResult = DecisionResult.model_validate_json(decision_row.snapshot_json)
        if (
            decision.kind != "assumption"
            or decision.resolution != "pending"
            or decision.revision != command.expected_revision
        ):
            raise Conflict("stale_assumption_revision")
        decision.resolution = "confirmed" if command.resolution == "confirm" else "rejected"
        decision.resolution_reason, decision.revision = command.reason, decision.revision + 1
        decision.resolved_by, decision.resolved_author, decision.resolved_at = (
            self.queries.actor.id,
            self.queries.actor.name,
            datetime.now(UTC),
        )
        decision_row.snapshot_json = decision.model_dump_json()
        risk_row: RiskRow | None = await self.queries.session.scalar(
            select(RiskRow).where(RiskRow.decision_id == decision_id).with_for_update()
        )
        if risk_row is None:
            raise Missing("risk")
        risk: RiskView = RiskView.model_validate_json(risk_row.snapshot_json)
        risk.status = "closed" if command.resolution == "confirm" else "realized"
        risk.resolution_reason = command.reason
        risk_row.snapshot_json = risk.model_dump_json()
        if command.resolution == "reject":
            await self.reopen(decision, command.reason, extractions)
        result: DecisionResult = decision.model_copy(update={"operation_id": command.operation_id})
        self.record("resolve", decision_id, command, result)
        return result

    async def _lock_resolution_runs(self, decision: DecisionRow) -> list[ExtractionRow]:
        linked: Select[UUID] = select(QuestionLinkRow.run_id).where(
            QuestionLinkRow.question_id == decision.question_id,
            QuestionLinkRow.revision == decision.question_revision,
        )
        # Lock every affected run before taking state/decision/question locks. An answer
        # can hold its own run while waiting for the shared question revision.
        query: Select[ExtractionRow] = (
            select(ExtractionRow)
            .where(
                ExtractionRow.task_id == self.queries.actor.task_id,
                or_(
                    ExtractionRow.id == decision.run_id,
                    and_(
                        ExtractionRow.id.in_(linked),
                        ExtractionRow.status.not_in(
                            (RunStatus.CANCELLED, RunStatus.CANCELLING, RunStatus.FAILED)
                        ),
                    ),
                ),
            )
            .order_by(ExtractionRow.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        extractions: list[ExtractionRow] = list(await self.queries.session.scalars(query))
        origin: ExtractionRow = next(row for row in extractions if row.id == decision.run_id)
        if origin.status in {RunStatus.CANCELLED, RunStatus.CANCELLING, RunStatus.FAILED}:
            raise Conflict("extraction_not_resumable")
        return extractions

    async def reopen(
        self, decision: DecisionResult, reason: str, extractions: list[ExtractionRow]
    ) -> None:
        identity: QuestionRow | None = await self.queries.session.get(
            QuestionRow, decision.question_id, with_for_update=True
        )
        old: QuestionRevisionRow = await self.queries.question(
            decision.run_id, decision.question_id, lock=True
        )
        if identity is None:
            raise Missing("question")
        question: ClarificationQuestion = ClarificationQuestion.model_validate_json(
            old.snapshot_json
        )
        question.previous_basis, question.basis = question.basis, reason
        question.revision, question.status = identity.revision + 1, "open"
        identity.revision = question.revision
        self.queries.session.add(
            QuestionRevisionRow(
                question_id=question.id,
                revision=question.revision,
                status="open",
                snapshot_json=question.model_dump_json(),
            )
        )
        extraction: ExtractionRow
        for extraction in extractions:
            await self._reopen_linked_run(extraction, question, decision.question_revision)

    async def _reopen_linked_run(
        self, extraction: ExtractionRow, question: ClarificationQuestion, expected_revision: int
    ) -> None:
        link: QuestionLinkRow | None = await self.queries.session.get(
            QuestionLinkRow, (extraction.id, question.id)
        )
        if link is None:
            raise Missing("question_link")
        if link.revision != expected_revision:
            return
        state: ClarificationRunRow = await self.queries.run(extraction.id, lock=True)
        link.revision = question.revision
        state.cycle += 1
        state.resume_pending = True
        state.resume_version += 1
        view: ExtractionView = ExtractionView.model_validate_json(extraction.snapshot_json)
        view.status = RunStatus.WAITING_INPUT
        extraction.status, extraction.snapshot_json = view.status.value, view.model_dump_json()
