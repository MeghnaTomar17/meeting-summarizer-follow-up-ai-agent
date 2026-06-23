# search-service — embeddings and vector retrieval

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/search-service ./backend/search-service
COPY backend/shared ./backend/shared

RUN chown -R appuser:appuser /app

ENV PYTHONPATH=/app/backend
ENV APP_ENV=production

WORKDIR /app/backend/search-service

USER appuser

EXPOSE 8003

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
