# =============================================================================
# domo-scheduled-ext-reporting
# Multi-stage Docker build with a slim runtime that includes a JRE for the
# bundled Domo CLI JAR (app/utils/domoUtil.jar).
# =============================================================================

# ---- Builder stage: install Python deps into an isolated layer ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install -r requirements.txt


# ---- Runtime stage ----
FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=local \
    PATH=/usr/local/bin:$PATH

WORKDIR /app

# default-jre-headless is required by the bundled Domo CLI JAR.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-jre-headless \
        tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY main.py ./
COPY app/ ./app/
COPY config/ ./config/

# Tini ensures clean PID 1 signal handling so cron / scheduler shut down nicely.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default: keep container alive so users can `docker compose exec app ...`.
# To run the in-container scheduler instead, override CMD:
#   command: ["python", "main.py", "--scheduler"]
CMD ["tail", "-f", "/dev/null"]
