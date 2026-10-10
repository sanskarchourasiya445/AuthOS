# =============================================================================
# AuthOS Multi-Stage Production Dockerfile
# Stage 1: Build modern React + TypeScript frontend
# Stage 2: Minimal, secure Python 3.13 runtime with explicit Alembic migrations
# =============================================================================

# --- Stage 1: Frontend Build ---
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python Backend Runtime ---
FROM python:3.13-slim AS runtime

# Install system dependencies (libpq for postgresql client, curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pinned Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root unprivileged service account
RUN useradd -m -u 1001 -s /bin/bash authos

# Copy application code and configuration
COPY contracts/ ./contracts/
COPY backend/ ./backend/
COPY data/ ./data/
COPY alembic.ini ./

# Copy compiled frontend distribution from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Set ownership to unprivileged user
RUN chown -R authos:authos /app

USER authos

# Health check using liveness probe
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

EXPOSE 8000

# Default entrypoint: Apply Alembic migrations to latest head, then start Uvicorn
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
