# gateway-service — API gateway (auth, routing, validation)
# TODO: Multi-stage build, non-root user, healthcheck

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/gateway-service ./backend/gateway-service
COPY backend/shared ./backend/shared
ENV PYTHONPATH=/app/backend
CMD ["uvicorn", "gateway-service.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
