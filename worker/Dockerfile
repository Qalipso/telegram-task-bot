# Build context = repo root (so the shared `core` package is available).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY core ./core
RUN pip install ./core
COPY worker ./worker
RUN pip install ./worker

CMD ["python", "-m", "aiwip_worker.main"]
