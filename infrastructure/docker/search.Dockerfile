# search-service — embeddings and vector retrieval
# TODO: Optimize image size; add model cache volume

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/search-service ./backend/search-service
COPY backend/shared ./backend/shared
ENV PYTHONPATH=/app/backend
CMD ["uvicorn", "search-service.main:app", "--host", "0.0.0.0", "--port", "8003"]
