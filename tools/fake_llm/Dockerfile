FROM python:3.13.9-slim@sha256:326df678c20c78d465db501563f3492d17c42a4afe33a1f2bf5406a1d56b0e86
WORKDIR /app
COPY tools/fake_llm/server.py ./server.py
USER 10001
CMD ["python", "server.py"]
