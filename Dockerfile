FROM node:22-slim AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 FRONTEND_DIST=/app/frontend/dist CACHE_DIR=/tmp/truck-cache
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/dist /app/frontend/dist
RUN useradd --create-home app
USER app
EXPOSE 8000
# One process, so the weather quota limiter sees every request. Threads handle
# concurrency, and the timeout allows for the limiter's longest wait.
CMD ["sh", "-c", "exec gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 8 --timeout 240"]
