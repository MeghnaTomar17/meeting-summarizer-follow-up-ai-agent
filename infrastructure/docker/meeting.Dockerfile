# meeting-service — meetings, uploads, transcripts
# TODO: Add ffmpeg for audio processing when implemented

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/meeting-service ./backend/meeting-service
COPY backend/shared ./backend/shared
ENV PYTHONPATH=/app/backend
CMD ["uvicorn", "meeting-service.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
