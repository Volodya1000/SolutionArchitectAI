from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
EXAMPLES_DIRECTORY: Final[Path] = REPOSITORY_ROOT / "docs" / "examples"
SUBJECT_HEADING: Final[str] = "## Часть I. Исходные требования к системе отчётности"
# Preserve the exact Russian requirement, including its single-letter prepositions.
OMITTED_SENTENCE: Final[str] = (
    " Запрос даты вне окна отклоняется с сообщением о допустимом диапазоне"  # noqa: RUF001
)
EDITORIAL_SUFFIX: Final[str] = (
    " Неполные вводные и отрицательные сценарии проверяются отдельно от этого полного примера."
)


def read_acceptance_input(filename: str) -> str:
    document_path: Path = EXAMPLES_DIRECTORY / "pr3" / filename
    assert document_path.is_file(), f"Missing PR 3 acceptance input: {document_path}"
    return document_path.read_text(encoding="utf-8")


def test_complete_input_preserves_all_original_subject_content() -> None:
    original: str = (EXAMPLES_DIRECTORY / "reporting-system.md").read_text(encoding="utf-8")
    original_subject: str = original[original.index(SUBJECT_HEADING) :]
    expected_subject: str = original_subject.replace(EDITORIAL_SUFFIX, "")
    complete: str = read_acceptance_input("reporting-system-complete.md")
    complete_subject: str = complete[complete.index(SUBJECT_HEADING) :]

    assert original_subject.count(EDITORIAL_SUFFIX) == 1
    assert complete_subject.split() == expected_subject.split()


def test_incomplete_input_omits_only_r04_out_of_window_response() -> None:
    complete: str = read_acceptance_input("reporting-system-complete.md")
    incomplete: str = read_acceptance_input("reporting-system-incomplete.md")
    r04_requirement: str = next(line for line in complete.splitlines() if "| R-04 |" in line)

    assert complete.count(OMITTED_SENTENCE) == 1
    assert OMITTED_SENTENCE in r04_requirement
    assert incomplete == complete.replace(OMITTED_SENTENCE, "", 1)


def test_inputs_do_not_reveal_expected_solution_or_completeness() -> None:
    filename: str
    for filename in ("reporting-system-complete.md", "reporting-system-incomplete.md"):
        content: str = read_acceptance_input(filename)
        assert "Ожидаемый результат" not in content
        assert "expected-result" not in content
        assert "Вводных достаточно" not in content
        assert "уточняющий диалог не моделируется" not in content
        assert "Неполные вводные и отрицательные сценарии" not in content
        assert "полного примера" not in content
