# syntax=docker/dockerfile:1
# Overcharge Desk — Deterministic Financial Control Infrastructure
# Multi-stage secure production container

FROM python:3.11-slim-bookworm AS production

# Set environment variables for Python and security
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/tools \
    APP_ENV=production \
    PORT=8000

# Install minimal OS dependencies for health checking and cleanup
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged application user and group (UID/GID 10001)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

WORKDIR /app

# Copy dependency manifest first for Docker layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code and assets
COPY domain/ ./domain/
COPY services/ ./services/
COPY tools/ ./tools/
COPY apps/ ./apps/
COPY seed/ ./seed/
COPY vendors/ ./vendors/
COPY contracts/ ./contracts/
COPY invoices/ ./invoices/
COPY cases/ ./cases/
COPY app.py LICENSE README.md ./

# Create runtime directories for persistence and set non-root ownership
RUN mkdir -p /app/cases /app/checkpoints /app/data && \
    chown -R appuser:appgroup /app

# Drop root privileges
USER appuser

# Health check probe validating Python Decimal, Argon2id, ledger, and storage
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python tools/health_check.py || exit 1

EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
