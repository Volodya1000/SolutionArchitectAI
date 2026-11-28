import re
from typing import Literal
from unicodedata import name


class SourceLanguageValidationFailure(ValueError):
    def __init__(self, field_path: str, expected_script: Literal["Cyrillic", "Latin"]) -> None:
        super().__init__("Keep the source language in every statement; do not translate it")
        self.field_path: str = field_path
        self.expected_script: Literal["Cyrillic", "Latin"] = expected_script

    @property
    def diagnostic(self) -> str:
        path: str = self.field_path if re.fullmatch(r"[A-Za-z_0-9.$]+", self.field_path) else "$"
        return (
            f"{path}: preserve the {self.expected_script} source language in every human-readable "
            "field; do not translate source prose"
        )[:200]


def script_counts(text: str) -> tuple[int, int]:
    cyrillic: int = 0
    latin: int = 0
    char: str
    for char in text:
        script: str = name(char, "")
        if "CYRILLIC" in script and char.isalpha():
            cyrillic += 1
        elif "LATIN" in script and char.isalpha():
            latin += 1
    return cyrillic, latin


def validate_source_language(source: str, text: str, *, field_path: str = "$") -> None:
    """Reject clear Cyrillic/Latin prose translation; allow names and mixed sources.

    This checks scripts, not arbitrary natural languages. Short identifiers and
    technical abbreviations are insufficient evidence for a language decision.
    """
    if text.strip() in source:
        return
    if text.isupper() and " " not in text.strip():
        return
    source_cyrillic: int
    source_latin: int
    text_cyrillic: int
    text_latin: int
    source_cyrillic, source_latin = script_counts(source)
    text_cyrillic, text_latin = script_counts(text)
    translated_to_latin: bool = (
        source_cyrillic >= 6
        and source_cyrillic > 2 * source_latin
        and text_latin >= 1
        and text_latin > 2 * text_cyrillic
    )
    translated_to_cyrillic: bool = (
        source_latin >= 6
        and source_latin > 2 * source_cyrillic
        and text_cyrillic >= 1
        and text_cyrillic > 2 * text_latin
    )
    if translated_to_latin or translated_to_cyrillic:
        raise SourceLanguageValidationFailure(
            field_path, "Cyrillic" if translated_to_latin else "Latin"
        )
