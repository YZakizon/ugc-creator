FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
