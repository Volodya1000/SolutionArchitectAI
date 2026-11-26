"""Score a saved extraction using an explicit human semantic mapping, without fuzzy matching."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from tools.extraction_evaluation_models import (
    Evaluation,
    GoldSet,
    ManualMapping,
    Metric,
    RunRecord,
)


def metric(numerator: int, denominator: int) -> Metric:
    return Metric(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
    )


def validate_mapping(run: RunRecord, gold: GoldSet, judgments: ManualMapping) -> None:
    predicted: set[UUID] = {item.id for item in run.requirements}
    gold_ids: set[str] = {item.id for item in gold.requirements}
    if len(predicted) != len(run.requirements) or len(gold_ids) != len(gold.requirements):
        raise ValueError("Duplicate prediction or gold IDs")
    if set(judgments.root) != predicted:
        raise ValueError("Every prediction needs exactly one manual judgment; empty list means FP")
    references: list[str]
    for references in judgments.root.values():
        validate_references(references, gold_ids)


def validate_references(references: list[str], gold_ids: set[str]) -> None:
    if len(references) != len(set(references)) or not set(references) <= gold_ids:
        raise ValueError("Manual judgments contain duplicate or unknown gold IDs")


def validate_counts(run: RunRecord) -> None:
    if run.coverage.processed_fragments > run.coverage.total_fragments:
        raise ValueError("Processed fragments exceed selected fragments")
    if run.progress.completed_parts > run.progress.total_parts:
        raise ValueError("Completed parts exceed selected parts")
    if run.progress.completed_parts > run.requests:
        raise ValueError("Validated saved parts exceed reserved requests")
    if run.validated_responses is not None and run.validated_responses > run.requests:
        raise ValueError("Validated responses exceed reserved requests")


def evaluate(run: RunRecord, gold: GoldSet, judgments: ManualMapping) -> Evaluation:
    validate_mapping(run, gold, judgments)
    validate_counts(run)
    matched_predictions: int = sum(bool(ids) for ids in judgments.root.values())
    matched_gold: set[str] = {reference for ids in judgments.root.values() for reference in ids}
    predicted_count: int = len(run.requirements)
    gold_count: int = len(gold.requirements)
    sources: int = sum(len(item.sources) for item in run.requirements)
    verified: int = sum(
        source.status == "verified" for item in run.requirements for source in item.sources
    )
    validated: int = (
        run.validated_responses
        if run.validated_responses is not None
        else run.progress.completed_parts
    )
    return Evaluation(
        run_id=run.id,
        run_created_at=run.created_at,
        measured_at=datetime.now(UTC),
        model=run.model,
        status=run.status,
        gold_source=gold.source,
        annotation_status=gold.annotation_status,
        metrics={
            "precision": metric(matched_predictions, predicted_count),
            "recall": metric(len(matched_gold), gold_count),
            "f1": metric(
                2 * matched_predictions * len(matched_gold),
                matched_predictions * gold_count + len(matched_gold) * predicted_count,
            ),
            "technical_source_validity": metric(verified, sources),
            "fragment_coverage": metric(
                run.coverage.processed_fragments, run.coverage.total_fragments
            ),
            "part_coverage": metric(run.progress.completed_parts, run.progress.total_parts),
            "structural_validation": metric(validated, run.requests),
        },
        false_positive_predictions=sorted(
            [key for key, references in judgments.root.items() if not references], key=str
        ),
        unmatched_gold=sorted({item.id for item in gold.requirements} - matched_gold),
        duplicate_gold_assignments=sum(len(ids) for ids in judgments.root.values())
        - len(matched_gold),
        reserved_requests=run.requests,
        network_failures=run.network_failures,
        corrections=run.corrections,
        elapsed_seconds=run.elapsed_seconds,
        validation_rate_basis=(
            "response_counter"
            if run.validated_responses is not None
            else "persisted_parts_lower_bound"
        ),
        coverage_complete=run.coverage.complete,
        notes=[
            "Precision counts reviewed candidates with any gold match; recall counts distinct gold IDs. "
            "Duplicate mappings are reported separately; no automatic semantic matching is performed.",
            "Source validity checks technical provenance, not whether a quote semantically supports a claim.",
            "When validated_responses is absent, structural_validation uses saved valid parts as a lower bound. "
            "Reserved requests can include cancellation or crash before an HTTP response.",
            "Zero denominator is null. Provisional annotations are not architect approval.",
        ],
    )


def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    key: str
    value: object
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not valid evaluation inputs")
        result[key] = value
    return result


def read_model[T: BaseModel](path: Path, schema: type[T]) -> T:
    value: str = path.read_text(encoding="utf-8")
    json.loads(value, object_pairs_hook=unique_keys)
    return schema.model_validate_json(value, strict=True)


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args: argparse.Namespace = parser.parse_args()
    run_path: Path = args.run
    gold_path: Path = args.gold
    mapping_path: Path = args.mapping
    output_path: Path | None = args.output
    try:
        result: Evaluation = evaluate(
            read_model(run_path, RunRecord),
            read_model(gold_path, GoldSet),
            read_model(mapping_path, ManualMapping),
        )
        rendered: str = result.model_dump_json(indent=2) + "\n"
        if output_path is None:
            print(rendered, end="")
        else:
            output_path.write_text(rendered, encoding="utf-8")
    except (OSError, ValueError):
        parser.exit(
            2, "Evaluation inputs are invalid; check IDs, full manual mapping and JSON schemas.\n"
        )


if __name__ == "__main__":
    main()
