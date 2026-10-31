# Multi-stage build for DataCraft Studio
# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Python Backend & Runtime
FROM python:3.12-slim AS runner
WORKDIR /app

# Install minimal OS dependencies for healthchecks and builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install backend Python dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend application source
COPY backend/ ./backend/

# Copy compiled frontend from builder stage
COPY --from=frontend-builder /app/dist /app/dist

# Set runtime environment variables
ENV PYTHONUNBUFFERED=1 \
    PUBLIC_DIR=/app/dist \
    REDIS_HOST=redis \
    REDIS_PORT=6379

WORKDIR /app/backend

EXPOSE 8000

# Default command runs FastAPI web service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
