from solution_architect_ai.application.models.extraction_models import PartResult, RequirementView


def merge_extraction_results(parts: list[PartResult]) -> list[RequirementView]:
    seen: set[str] = set()
    merged: list[RequirementView] = []
    part: PartResult
    requirement: RequirementView
    for part in parts:
        for requirement in part.requirements:
            identity: str = requirement.model_dump_json(exclude={"id"})
            if identity not in seen:
                seen.add(identity)
                merged.append(requirement)
    return merged
