# syntax=docker/dockerfile:1.7

# --- Stage 1: build ---------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Stage 2: runtime -------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 1000 deep_agent
WORKDIR /app

COPY --from=build --chown=deep_agent:deep_agent /app/.venv /app/.venv
COPY --chown=deep_agent:deep_agent src ./src
COPY --chown=deep_agent:deep_agent domains ./domains
COPY --chown=deep_agent:deep_agent pyproject.toml README.md ./

USER deep_agent

EXPOSE 8000

CMD ["deep-agent", "serve", "--host", "0.0.0.0", "--port", "8000"]
