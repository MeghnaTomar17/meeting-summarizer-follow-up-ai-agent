# meeting-service — meetings, uploads, transcripts

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/meeting-service ./backend/meeting-service
COPY backend/shared ./backend/shared

RUN chown -R appuser:appuser /app

ENV PYTHONPATH=/app/backend
ENV APP_ENV=production

WORKDIR /app/backend/meeting-service

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
