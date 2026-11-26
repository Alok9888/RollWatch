# Stage 1: Build virtual environment with dependencies
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Clean non-root runtime image
FROM python:3.12-slim AS runtime

ARG GIT_SHA=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    GIT_SHA=${GIT_SHA} \
    ROLLWATCH_DB_PATH=/data/rollwatch.db

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system --gid 1001 rollwatch && \
    useradd --system --uid 1001 --gid rollwatch --home /app rollwatch && \
    mkdir -p /app /data && \
    chown -R rollwatch:rollwatch /app /data

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=rollwatch:rollwatch app ./app

USER rollwatch

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
