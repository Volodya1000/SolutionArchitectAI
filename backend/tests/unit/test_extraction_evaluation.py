import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from tools.evaluate_extraction import evaluate, main, read_model
from tools.extraction_evaluation_models import (
    Coverage,
    Evaluation,
    GoldRequirement,
    GoldSet,
    ManualMapping,
    Prediction,
    Progress,
    RunRecord,
    SourceEvidence,
)


def run_record() -> RunRecord:
    return RunRecord(
        id=UUID(int=1),
        created_at=datetime(2026, 11, 26, tzinfo=UTC),
        model="synthetic-test",
        status="completed",
        coverage=Coverage(complete=True, total_fragments=2, processed_fragments=2),
        progress=Progress(completed_parts=2, total_parts=2),
        requirements=[
            Prediction(id=UUID(int=2), sources=[SourceEvidence(status="verified")]),
            Prediction(id=UUID(int=3), sources=[SourceEvidence(status="unverified")]),
            Prediction(id=UUID(int=4), sources=[]),
        ],
        requests=3,
        elapsed_seconds=12,
    )


def gold_set() -> GoldSet:
    return GoldSet(
        source="backend/tests/fixtures/pr2/brd-example.md",
        annotation_status="provisional",
        requirements=[
            GoldRequirement(
                id="FR-1", category="functional", description="First", quotes=["First"]
            ),
            GoldRequirement(
                id="FR-2", category="functional", description="Second", quotes=["Second"]
            ),
            GoldRequirement(
                id="FR-3", category="functional", description="Third", quotes=["Third"]
            ),
        ],
    )


def test_semantic_metrics_use_manual_mapping_and_show_numerators() -> None:
    result: Evaluation = evaluate(
        run_record(),
        gold_set(),
        ManualMapping(root={UUID(int=2): ["FR-1"], UUID(int=3): ["FR-2"], UUID(int=4): []}),
    )
    assert result.metrics["precision"].numerator == 2
    assert result.metrics["precision"].denominator == 3
    assert result.metrics["recall"].value == pytest.approx(2 / 3)
    assert result.metrics["f1"].value == pytest.approx(2 / 3)
    assert result.metrics["technical_source_validity"].value == 0.5
    assert result.false_positive_predictions == [UUID(int=4)]
    assert result.unmatched_gold == ["FR-3"]
    assert result.annotation_status == "provisional"
    assert result.model == "synthetic-test"


def test_duplicate_predictions_do_not_inflate_distinct_gold_recall() -> None:
    result: Evaluation = evaluate(
        run_record(),
        gold_set(),
        ManualMapping(root={UUID(int=2): ["FR-1"], UUID(int=3): ["FR-1"], UUID(int=4): []}),
    )
    assert result.metrics["recall"].numerator == 1
    assert result.metrics["recall"].denominator == 3
    assert result.duplicate_gold_assignments == 1


@pytest.mark.parametrize(
    "mapping",
    [
        {UUID(int=2): ["FR-1"]},
        {UUID(int=2): ["FR-1"], UUID(int=3): ["unknown"], UUID(int=4): []},
        {UUID(int=2): ["FR-1"], UUID(int=3): ["FR-2"], UUID(int=4): [], UUID(int=99): []},
    ],
)
def test_missing_or_unknown_manual_judgments_cannot_be_silently_scored(
    mapping: dict[UUID, list[str]],
) -> None:
    with pytest.raises(ValueError, match="judgment"):
        evaluate(run_record(), gold_set(), ManualMapping(root=mapping))


@pytest.mark.parametrize("name", ["brd-example", "adversarial", "reporting-system"])
def test_provisional_fixture_quotes_are_present_in_independent_source(name: str) -> None:
    repository: Path = Path(__file__).resolve().parents[3]
    fixtures: Path = repository / "backend" / "tests" / "fixtures" / "pr2"
    gold: GoldSet = read_model(fixtures / f"{name}.gold.json", GoldSet)
    source: str = (repository / gold.source).read_text(encoding="utf-8")
    assert gold.annotation_status == "provisional"
    assert len({item.id for item in gold.requirements}) == len(gold.requirements)
    for item in gold.requirements:
        assert all(quote in source for quote in item.quotes)


def test_cli_reads_saved_run_and_writes_machine_readable_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved_run: Path = tmp_path / "run.json"
    saved_gold: Path = tmp_path / "gold.json"
    saved_mapping: Path = tmp_path / "mapping.json"
    output: Path = tmp_path / "evaluation.json"
    saved_run.write_text(run_record().model_dump_json(), encoding="utf-8")
    saved_gold.write_text(gold_set().model_dump_json(), encoding="utf-8")
    saved_mapping.write_text(
        ManualMapping(
            root={UUID(int=2): ["FR-1"], UUID(int=3): [], UUID(int=4): []}
        ).model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate",
            "--run",
            str(saved_run),
            "--gold",
            str(saved_gold),
            "--mapping",
            str(saved_mapping),
            "--output",
            str(output),
        ],
    )
    main()
    report: Evaluation = read_model(output, Evaluation)
    assert report.metrics["precision"].numerator == 1
    assert report.metrics["recall"].denominator == 3
    assert report.validation_rate_basis == "persisted_parts_lower_bound"


def test_unknown_retry_counts_and_zero_denominators_remain_unknown() -> None:
    record: RunRecord = RunRecord(
        id=UUID(int=1),
        created_at=datetime(2026, 11, 26, tzinfo=UTC),
        model="test",
        status="failed",
        coverage=Coverage(complete=False, total_fragments=0, processed_fragments=0),
        progress=Progress(total_parts=0, completed_parts=0),
        requirements=[],
        requests=0,
        elapsed_seconds=0,
    )
    gold: GoldSet = GoldSet(source="empty", annotation_status="provisional", requirements=[])
    report: Evaluation = evaluate(record, gold, ManualMapping(root={}))
    assert report.metrics["precision"].value is None
    assert report.metrics["recall"].value is None
    assert report.metrics["f1"].value is None
    assert report.network_failures is None
    assert report.corrections is None
