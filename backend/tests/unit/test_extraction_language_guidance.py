import json
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import BaseModel

from solution_architect_ai.application.context.context_models import ContextPack, ContextPolicy
from solution_architect_ai.application.context.extraction_context_builder import (
    ExtractionContextBuilder,
)
from solution_architect_ai.application.models.extraction_models import RequirementsExtraction
from solution_architect_ai.application.models.structured_models import (
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
)
from solution_architect_ai.application.prompts.structured_prompt import (
    CORRECTION_PROMPT,
    render_messages,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser


def context_for(source: str) -> ContextPack:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), source.encode(), "requirements.md", "text/markdown"
    )
    return ExtractionContextBuilder(
        LangChainTokenCounter(2, chat_prompt=False), ContextPolicy(12288, 6912, 256)
    ).build((document,), "")


class QuestionPayload(BaseModel):
    question: str


@pytest.mark.parametrize("schema", [RequirementsExtraction, QuestionPayload])
@pytest.mark.parametrize("mode", list(StructuredMode))
def test_cyrillic_source_gets_trusted_language_guidance_after_untrusted_data(
    schema: type[BaseModel], mode: StructuredMode
) -> None:
    source: str = "Система должна сохранять журнал аудита."
    context: ContextPack = context_for(source)
    request: StructuredRequest = StructuredRequest(
        context.parts[0].messages, ModelProfile("model", mode, 12288, 6912, 256)
    )
    messages: tuple[StructuredMessage, ...] = render_messages(request, schema)

    assert messages[-1].role == MessageRole.SYSTEM
    assert "normalized_text" in messages[-1].content
    assert source not in messages[-1].content
    assert messages[-2].role == MessageRole.USER
    assert source in json.dumps(json.loads(messages[-2].content), ensure_ascii=False)
    assert context.parts[0].fragments[0].text == source


def test_latin_source_does_not_get_russian_language_guidance() -> None:
    source: str = "The service shall keep audit entries."
    context: ContextPack = context_for(source)
    messages: tuple[StructuredMessage, ...] = render_messages(
        StructuredRequest(
            context.parts[0].messages,
            ModelProfile("model", StructuredMode.NATIVE_JSON_SCHEMA, 12288, 6912, 256),
        ),
        RequirementsExtraction,
    )

    assert messages[-1].role == MessageRole.USER
    assert len(messages) == 2
    assert context.parts[0].fragments[0].text == source


def test_english_correction_does_not_hide_the_language_of_source_prose() -> None:
    context: ContextPack = context_for("Система должна сохранять журнал аудита.")
    request: StructuredRequest = StructuredRequest(
        context.parts[0].messages,
        ModelProfile("model", StructuredMode.NATIVE_JSON_SCHEMA, 12288, 6912, 256),
    )
    corrected: StructuredRequest = replace(
        request,
        messages=(*request.messages, StructuredMessage(MessageRole.USER, CORRECTION_PROMPT)),
    )
    messages: tuple[StructuredMessage, ...] = render_messages(corrected, RequirementsExtraction)

    assert messages[-1].role == MessageRole.SYSTEM
    assert messages[-2].content == CORRECTION_PROMPT
    assert "normalized_text" in messages[-1].content
