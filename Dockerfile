# OPB Index Options Buying Bot v2.59.1
# ─────────────────────────────────────────────────────────────────────────────
# Multi-stage build:
#   builder  — installs heavy ML/science deps into a venv
#   runtime  — slim image that copies the venv + source
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps needed to compile some wheels (lightgbm, numpy, reportlab)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated venv so the runtime stage only needs to copy it
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip==24.2 wheel && \
    pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="OPB Bot"
LABEL version="2.59.1"
LABEL org.opencontainers.image.source="https://github.com/opb/index-options-bot"
LABEL org.opencontainers.image.description="NSE Index Options Buying Bot — automated signal generation, risk management, and trade execution"

# Runtime shared libs required by lightgbm / numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

# (pip is pinned in the builder stage; runtime copies the venv so no pip needed here)

# Non-root user for safety
RUN useradd --create-home --shell /bin/bash opb
WORKDIR /app

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY --chown=opb:opb . .

# Persistent data directories (mounted as Docker volumes in production)
RUN mkdir -p /data/db /data/models /data/reports /data/logs && \
    chown -R opb:opb /data

# Default env overrides — all sensitive values come from the environment
ENV OPBUYING_TRADES_DB=/data/db/trades.db \
    OPBUYING_OI_SNAPSHOT_DB_PATH=/data/db/oi_snapshots.db \
    OPBUYING_ML_TRACKER_DB_PATH=/data/db/ml_tracker.db \
    OPBUYING_DRIFT_DB_PATH=/data/db/ml_tracker.db \
    OPBUYING_ML_MODEL_PATH=/data/models/signal_classifier.pkl \
    OPBUYING_REPORT_OUTPUT_DIR=/data/reports \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Kolkata

# Supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/opb.conf

# Expose the web dashboard port (disabled inside container unless cfg enables it)
EXPOSE 8765

# Data volumes
VOLUME ["/data/db", "/data/models", "/data/reports", "/data/logs"]

USER opb

# Health check: verify core + enterprise dashboard modules are importable,
# then try HTTP health endpoint if dashboard is running. Logic lives in
# scripts/docker_healthcheck.py (the repo is COPYed to /app) so the instruction
# stays a single valid line — raw newlines inside HEALTHCHECK CMD break the
# Docker parser ("unknown instruction: import").
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python", "scripts/docker_healthcheck.py"]

# Default: run via supervisord (manages bot + optional dashboard)
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/opb.conf", "-n"]
