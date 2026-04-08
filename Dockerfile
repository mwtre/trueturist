# TrueTurist: flight-explorer + vendored fli (monorepo root)
# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY fli /app/fli
COPY flight-explorer /app/flight-explorer

RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r /app/flight-explorer/requirements.txt \
    && pip install --no-cache-dir -e /app/fli

WORKDIR /app/flight-explorer

ENV PYTHONUNBUFFERED=1
EXPOSE 8765

# Render sets PORT at runtime; default for local docker run -p 8765:8765
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8765}"]
