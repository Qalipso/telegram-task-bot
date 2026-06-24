# Build context = repo root (so the shared `core` package is available).
FROM python:3.12-alpine AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev python3-dev

WORKDIR /tmp

COPY core ./core
RUN pip install --user --no-cache-dir ./core

COPY worker ./worker
RUN pip install --user --no-cache-dir ./worker

FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/appuser/.local/lib/python3.12/site-packages \
    PATH=/home/appuser/.local/bin:$PATH

RUN addgroup -g 1000 appuser && adduser -D -u 1000 -G appuser appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

USER appuser

CMD ["python", "-m", "aiwip_worker.main"]
