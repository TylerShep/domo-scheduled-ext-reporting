# =============================================================================
# domo-scheduled-ext-reporting
# Multi-stage Docker build with a slim runtime. JRE is optional -- only the
# legacy JAR engine needs it; the default REST engine has zero JVM deps.
#
# Build with:
#   docker build .                          # default (no JRE, REST-only)
#   docker build --build-arg INSTALL_JRE=true .   # include JRE for JAR engine
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

ARG INSTALL_JRE=false

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=local \
    DOMO_ENGINE=rest \
    PATH=/usr/local/bin:$PATH

WORKDIR /app

# Always install tini for signal handling. JRE only when requested.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && if [ "$INSTALL_JRE" = "true" ]; then \
         apt-get install -y --no-install-recommends default-jre-headless; \
       fi \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY main.py ./
COPY app/ ./app/
COPY config/ ./config/

# When the JAR engine is requested, fetch + verify the CLI JAR during
# the build so the runtime image is self-contained.  Requires curl, which
# we install temporarily and uninstall in the same layer.
RUN if [ "$INSTALL_JRE" = "true" ]; then \
      python -m app.engines.jar_download_cli || \
        (echo "JAR download failed (see app/engines/JAR_VERSION.json)" && exit 1); \
    fi

# Web UI port (only used when CMD is `python main.py --serve`).
EXPOSE 8765

# Tini ensures clean PID 1 signal handling so cron / scheduler shut down nicely.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default: keep container alive so users can `docker compose exec app ...`.
# To run the in-container scheduler instead, override CMD:
#   command: ["python", "main.py", "--scheduler"]
# To run the web UI:
#   command: ["python", "main.py", "--serve"]
CMD ["tail", "-f", "/dev/null"]
