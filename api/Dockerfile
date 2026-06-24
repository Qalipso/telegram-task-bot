# Build context = repo root (so the shared `core` package is available).
FROM python:3.12-alpine AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev python3-dev

WORKDIR /tmp

COPY core ./core
RUN pip install --user --no-cache-dir ./core

COPY api ./api
RUN pip install --user --no-cache-dir ./api

FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/appuser/.local/lib/python3.12/site-packages \
    PATH=/home/appuser/.local/bin:$PATH

RUN addgroup -g 1000 appuser && adduser -D -u 1000 -G appuser appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser scripts/entrypoint-api.sh /app/entrypoint.py

RUN chmod +x /app/entrypoint.py

USER appuser

EXPOSE 8000
CMD ["python", "/app/entrypoint.py"]
