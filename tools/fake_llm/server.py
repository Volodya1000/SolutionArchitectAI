"""Deterministic OpenAI-compatible endpoint. Test controls require the fake profile."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final, Literal, TypedDict

LISTEN_HOST: Final[str] = "0.0.0.0"  # nosec B104
MODEL: Final[str] = "fake-chat"
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


def extracted_requirements(body: object) -> str:
    requirements: list[dict[str, object]] = []
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
            self.write_completion(prompt)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def structured(self, body: dict[str, object], prompt: str) -> None:
        answer: str = extracted_requirements(body)
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
            return

    def write_completion(self, prompt: str) -> None:
        answer: str = (
            ""
            if "[empty]" in prompt
            else (
                "Это ответ локальной тестовой модели. Разделите ответственность компонентов, "
                "зафиксируйте требования и проверьте границы взаимодействий. " + prompt
            )
        )
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
