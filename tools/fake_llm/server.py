"""Deterministic OpenAI-compatible endpoint. Test controls require the fake profile."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"object": "list", "data": [
            {"id": "fake-chat", "object": "model", "owned_by": "local-test"}]}).encode())

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        prompt = body["messages"][-1]["content"]
        if "[error]" in prompt:
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        answer = "" if "[empty]" in prompt else (
            "Это ответ локальной тестовой модели. Разделите ответственность компонентов, "
            "зафиксируйте требования и проверьте границы взаимодействий. " + prompt
        )
        if "[slow]" in prompt:
            answer *= 40
        try:
            for offset in range(0, len(answer), 8):
                self.chunk({"content": answer[offset:offset+8]}, None)
                time.sleep(0.03)
                if "[disconnect]" in prompt and offset > 32:
                    self.close_connection = True
                    return
            self.chunk({}, "length" if "[truncated]" in prompt else "stop")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def chunk(self, delta: dict[str, str], finish: str | None) -> None:
        item = {"id": "fake-response", "object": "chat.completion.chunk", "created": 1,
            "model": "fake-chat", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        self.wfile.write(("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode())
        self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
