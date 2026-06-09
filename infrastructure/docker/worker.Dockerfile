# worker-service — Celery/RQ background jobs
# TODO: Separate worker and beat containers in compose

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/worker-service ./backend/worker-service
COPY backend/shared ./backend/shared
ENV PYTHONPATH=/app/backend
CMD ["celery", "-A", "worker-service.queue.celery_app:celery_app", "worker", "--loglevel=info"]
