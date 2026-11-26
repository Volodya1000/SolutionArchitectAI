FROM python:3.13.9-slim@sha256:326df678c20c78d465db501563f3492d17c42a4afe33a1f2bf5406a1d56b0e86 AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
COPY backend/alembic.ini ./
RUN uv sync --locked --no-dev && mkdir -p /data/git /data/files && chmod -R g=u /data /app
ENV PATH="/app/backend/.venv/bin:$PATH" SAA_CONFIG_ROOT=/app
USER 10001:0
CMD ["python", "-m", "solution_architect_ai.di.server"]

FROM base AS test
USER 0
RUN uv sync --locked
COPY backend/tests ./tests
COPY backend/.importlinter backend/.flake8 ./
USER 10001:0
