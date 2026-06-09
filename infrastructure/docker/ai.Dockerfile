# ai-service — agents, pipelines, LLM integrations
# TODO: Pin model SDK versions; optional GPU base image

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ai-service ./backend/ai-service
COPY backend/shared ./backend/shared
ENV PYTHONPATH=/app/backend
CMD ["uvicorn", "ai-service.main:app", "--host", "0.0.0.0", "--port", "8002"]
