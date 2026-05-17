# OPB Index Options Buying Bot v2.43
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
RUN pip install --upgrade pip wheel && \
    pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="OPB Bot"
LABEL version="2.43"

# Runtime shared libs required by lightgbm / numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

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

# Health check: verify core + hardening modules are importable
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "
import sys
modules = [
    'core.token_refresh_service',
    'core.market_warmup',
    'core.ws_feed_manager',
    'core.kite_ticker_feed',
    'core.ltp_resolver',
    'core.metrics_exporter',
    'core.safety_state',
    'core.health_checker',
]
for m in modules:
    __import__(m)
print('OK')
" || exit 1

# Default: run via supervisord (manages bot + optional dashboard)
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/opb.conf", "-n"]
