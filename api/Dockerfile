# Build context = repo root (so the shared `core` package is available).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the shared core first (its own layer for caching), then the API.
COPY core ./core
RUN pip install ./core
COPY api ./api
RUN pip install ./api

EXPOSE 8000
CMD ["uvicorn", "aiwip_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
