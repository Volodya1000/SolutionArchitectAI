"""Deterministic OpenAI-compatible endpoint. Test controls require the fake profile."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final, Literal, TypedDict

LISTEN_HOST: Final[str] = "0.0.0.0"  # nosec B104
MODEL: Final[str] = "fake-chat"
MANDATORY_CONFLICT_MARKER: Final[str] = "[clarification:mandatory-conflict]"
type FinishReason = Literal["length", "stop"]


class CompletionChoice(TypedDict):
    index: int
    delta: dict[str, str]
    finish_reason: FinishReason | None


class CompletionChunk(TypedDict):
    id: str
    object: str
    created: int
    model: str
    choices: list[CompletionChoice]


def last_prompt(body: object) -> str:
    if not isinstance(body, dict):
        raise ValueError("Expected a request object")
    messages: object = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Expected at least one message")
    last: object = messages[-1]
    if not isinstance(last, dict):
        raise ValueError("Expected a message object")
    prompt: object = last.get("content")
    if not isinstance(prompt, str):
        raise ValueError("Expected text message content")
    return prompt


def document_fragments(body: object) -> list[dict[str, str]]:
    if not isinstance(body, dict):
        return []
    messages: object = body.get("messages")
    if not isinstance(messages, list):
        return []
    return [fragment for message in messages for fragment in message_fragments(message)]


def message_fragments(message: object) -> list[dict[str, str]]:
    if not isinstance(message, dict):
        return []
    content: object = message.get("content")
    if not isinstance(content, str):
        return []
    try:
        payload: object = json.loads(content)
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    values: object = payload.get("fragments")
    if not isinstance(values, list):
        return []
    return [item for value in values if (item := text_fragment(value)) is not None]


def text_fragment(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    identifier: object = value.get("fragment_id")
    content: object = value.get("text")
    if isinstance(identifier, str) and isinstance(content, str):
        return {"fragment_id": identifier, "text": content}
    return None


def controlled_conflict_evidence(fragments: list[dict[str, str]]) -> list[dict[str, str]]:
    if not any(MANDATORY_CONFLICT_MARKER in fragment["text"] for fragment in fragments):
        return []
    return [
        {"fragment_id": fragment["fragment_id"], "quote": fragment["text"][:2000]}
        for fragment in fragments
        if fragment["text"].strip() and MANDATORY_CONFLICT_MARKER not in fragment["text"]
    ][:2]


def extracted_requirements(body: object) -> str:
    evidence: list[dict[str, str]] = controlled_conflict_evidence(document_fragments(body))
    if len(evidence) == 2:
        return json.dumps(
            {
                "requirements": [],
                "gaps": [],
                "contradictions": [
                    {
                        "description": "Требование противоречит обязательному правилу",
                        "evidence": evidence,
                    }
                ],
            },
            ensure_ascii=False,
        )
    requirements: list[dict[str, object]] = []
    fragment: dict[str, str]
    for fragment in document_fragments(body):
        text: str = fragment["text"]
        if text.strip():
            quote: str = text[:2000]
            requirements.append(
                {
                    "category": "non_functional"
                    if "NFR" in text or "SLA" in text
                    else "functional",
                    "original_text": quote,
                    "normalized_text": quote,
                    "evidence": [{"fragment_id": fragment["fragment_id"], "quote": quote}],
                }
            )
    return json.dumps(
        {"requirements": requirements, "gaps": [], "contradictions": []}, ensure_ascii=False
    )


def request_payloads(body: object) -> list[dict[str, object]]:
    if not isinstance(body, dict):
        return []
    messages: object = body.get("messages")
    if not isinstance(messages, list):
        return []
    return [payload for message in messages if (payload := message_payload(message)) is not None]


def message_payload(message: object) -> dict[str, object] | None:
    if not isinstance(message, dict):
        return None
    content: object = message.get("content")
    if not isinstance(content, str):
        return None
    try:
        payload: object = json.loads(content)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def clarification_payload(body: object) -> dict[str, object] | None:
    return next(
        (payload for payload in request_payloads(body) if payload.get("role") == "clarification"),
        None,
    )


def structured_answer(body: object) -> str:
    if any(payload.get("role") == "conflict_assessment" for payload in request_payloads(body)):
        conflict_evidence: list[dict[str, str]] = controlled_conflict_evidence(
            document_fragments(body)
        )
        return json.dumps(
            {
                "status": "confirmed" if len(conflict_evidence) == 2 else "candidate",
                "reason": "Требование противоречит обязательному правилу. Требуется фактическое урегулирование."
                if len(conflict_evidence) == 2
                else "Недостаточно исходных утверждений для подтверждения конфликта",
                "evidence": conflict_evidence if len(conflict_evidence) == 2 else [],
            },
            ensure_ascii=False,
        )
    if any(payload.get("role") == "clarification_review" for payload in request_payloads(body)):
        evidence: list[dict[str, str]] = [
            {"fragment_id": fragment["fragment_id"], "quote": fragment["text"]}
            for fragment in document_fragments(body)
            if "Запрос даты вне окна отклоняется" in fragment["text"]
        ]
        return json.dumps(
            {
                "resolved": bool(evidence),
                "reason": "Проверены выбранные источники",
                "evidence": evidence,
            },
            ensure_ascii=False,
        )
    payload: dict[str, object] | None = clarification_payload(body)
    return (
        clarification_questions(body, payload)
        if payload is not None
        else extracted_requirements(body)
    )


def clarification_questions(body: object, payload: dict[str, object]) -> str:
    fragments: list[dict[str, str]] = document_fragments(body)
    if any(MANDATORY_CONFLICT_MARKER in fragment["text"] for fragment in fragments):
        return json.dumps({"questions": []})
    return source_questions(fragments, payload)


def source_questions(fragments: list[dict[str, str]], payload: dict[str, object]) -> str:
    source_text: str = " ".join(fragment["text"] for fragment in fragments)
    questions: list[dict[str, object]] = []
    incomplete: bool = (
        "R-04" in source_text and "Запрос даты вне окна отклоняется" not in source_text
    )
    controlled: bool = "[clarification:" in source_text
    if incomplete or controlled:
        count: int = 2 if "[clarification:two]" in source_text else 1
        candidates: object = payload.get("requirements")
        requirements: list[object] = candidates if isinstance(candidates, list) else []
        index: int
        for index in range(count):
            fragment: dict[str, str] = next(
                (item for item in fragments if "R-04" in item["text"]),
                fragments[min(index, len(fragments) - 1)],
            )
            requirement_id: str | None = matching_requirement(
                requirements, fragment["fragment_id"], index
            )
            if requirement_id is not None:
                questions.append(
                    {
                        "gap_key": f"query:outside-window:{index}",
                        "text": "Как система реагирует на запрос даты вне окна?",
                        "basis": "Срок хранения известен, но реакция на дату вне окна не задана.",
                        "dependent_decision": "Проверка допустимости запроса сводки",
                        "blocking": "[clarification:nonblocking]" not in source_text,
                        "requirement_ids": [requirement_id],
                        "evidence": [
                            {
                                "fragment_id": fragment["fragment_id"],
                                "quote": fragment["text"][:2000],
                            }
                        ],
                    }
                )
    return json.dumps({"questions": questions}, ensure_ascii=False)


def matching_requirement(requirements: list[object], fragment_id: str, index: int) -> str | None:
    identities: list[tuple[str, list[str]]] = [
        identity for value in requirements if (identity := requirement_identity(value)) is not None
    ]
    matches: list[str] = [
        identifier for identifier, fragments in identities if fragment_id in fragments
    ]
    if matches:
        return matches[min(index, len(matches) - 1)]
    return identities[0][0] if identities else None


def requirement_identity(value: object) -> tuple[str, list[str]] | None:
    if not isinstance(value, dict):
        return None
    identifier: object = value.get("id")
    fragments: object = value.get("fragment_ids")
    if not isinstance(identifier, str) or not isinstance(fragments, list):
        return None
    return identifier, [fragment for fragment in fragments if isinstance(fragment, str)]


def discussion_answer(body: object) -> str | None:
    payload: dict[str, object] | None = next(
        (item for item in request_payloads(body) if "source_fragments" in item), None
    )
    if payload is None:
        return None
    fragments: object = payload.get("source_fragments")
    subject: object = payload.get("subject")
    if not isinstance(fragments, list) or not isinstance(subject, dict):
        return None
    analysis_id: object = subject.get("analysis_id")
    links: list[str] = [
        link
        for fragment in fragments
        if (link := discussion_citation(fragment, analysis_id)) is not None
    ]
    return (
        "Срок хранения уже указан в R-03: 30 дней. Уточнить нужно реакцию системы на запрос даты вне этого окна в R-04. Переписка не сохраняет ответ автоматически. "
        + " ".join(links)
    )


def discussion_citation(fragment: object, analysis_id: object) -> str | None:
    if not isinstance(fragment, dict):
        return None
    version_id: object = fragment.get("version_id")
    fragment_id: object = fragment.get("fragment_id")
    quote: object = fragment.get("quote")
    if isinstance(fragment_id, str) and fragment_id.startswith("f") and isinstance(quote, str):
        labels: list[str] = [label for label in ("R-03", "R-04") if label in quote]
        return " ".join(f"[{label}](ref:{fragment_id})" for label in labels)
    if (
        not isinstance(version_id, str)
        or not isinstance(fragment_id, str)
        or not isinstance(quote, str)
    ):
        return None
    suffix: str = f"&run={analysis_id}" if isinstance(analysis_id, str) else ""
    labels = [label for label in ("R-03", "R-04") if label in quote]
    return " ".join(
        f"[{label}](/documents?version={version_id}&fragment={fragment_id}{suffix})"
        for label in labels
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        payload: dict[str, str | list[dict[str, str]]] = {
            "object": "list",
            "data": [{"id": MODEL, "object": "model", "owned_by": "local-test"}],
        }
        self.wfile.write(json.dumps(payload).encode())

    def do_POST(self) -> None:
        try:
            size: int = int(self.headers.get("Content-Length", "0"))
            if size < 0:
                raise ValueError("Expected a nonnegative request size")
            body: object = json.loads(self.rfile.read(size))
            prompt: str = last_prompt(body)
        except ValueError:
            self.send_error(400)
            return
        if "[error]" in prompt:
            self.send_error(503)
            return
        if isinstance(body, dict) and not body.get("stream", False):
            self.structured(body, prompt)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.write_completion(prompt, body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def structured(self, body: dict[str, object], prompt: str) -> None:
        answer: str = structured_answer(body)
        if "[slow]" in prompt:
            time.sleep(2)
        if "[invalid-json]" in prompt:
            answer = "{bad json"
        if "[empty]" in prompt:
            answer = ""
        payload: dict[str, object] = {
            "id": "fake-structured",
            "object": "chat.completion",
            "created": 1,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "length" if "[truncated]" in prompt else "stop",
                }
            ],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode())
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def write_completion(self, prompt: str, body: object = None) -> None:
        answer: str = (
            ""
            if "[empty]" in prompt
            else (
                "Это ответ локальной тестовой модели. Разделите ответственность компонентов, "
                "зафиксируйте требования и проверьте границы взаимодействий. " + prompt
            )
        )
        grounded: str | None = discussion_answer(body)
        if grounded is not None and "[empty]" not in prompt:
            answer = grounded
        if "[slow]" in prompt:
            answer *= 40
        offset: int
        for offset in range(0, len(answer), 8):
            self.chunk({"content": answer[offset : offset + 8]}, None)
            time.sleep(0.03)
            if "[disconnect]" in prompt and offset > 32:
                self.close_connection = True
                return
        self.chunk({}, "length" if "[truncated]" in prompt else "stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def chunk(self, delta: dict[str, str], finish: FinishReason | None) -> None:
        choice: CompletionChoice = {
            "index": 0,
            "delta": delta,
            "finish_reason": finish,
        }
        item: CompletionChunk = {
            "id": "fake-response",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": MODEL,
            "choices": [choice],
        }
        self.wfile.write(("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode())
        self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer((LISTEN_HOST, 8000), Handler).serve_forever()
