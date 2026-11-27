from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    StoredModelProfile,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
)
from solution_architect_ai.config.models import LLMSettings
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.extractions.extraction_store import extraction_view

PROFILE: Final[StoredModelProfile] = StoredModelProfile.model_validate(
    LLMSettings().model_dump(mode="json", exclude={"api_key"})
)


def test_old_snapshot_exposes_exact_command_even_when_result_has_no_requirements() -> None:
    version_id: UUID = uuid4()
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(), version_ids=[version_id], analysis_scope="Бронирования"
    )
    snapshot: ExtractionView = ExtractionView(
        id=uuid4(),
        status=RunStatus.COMPLETED,
        progress=ExtractionProgress(),
        error_code=None,
        created_at=datetime.now(UTC),
        model=PROFILE.model,
        model_profile=PROFILE,
        coverage=CoverageView(),
        requirements=[],
        contract_version=CONTRACT_VERSION,
        prompt_version=PROMPT_VERSION,
    )
    row: ExtractionRow = ExtractionRow(
        command_json=command.model_dump_json(),
        snapshot_json=snapshot.model_dump_json(
            exclude={"version_ids", "analysis_scope", "configuration_current"}
        ),
        requests=1,
        network_failures=0,
        corrections=0,
    )
    view: ExtractionView = extraction_view(row)
    assert view.version_ids == [version_id]
    assert view.analysis_scope == "Бронирования"
    assert row.snapshot_json == snapshot.model_dump_json(
        exclude={"version_ids", "analysis_scope", "configuration_current"}
    )
