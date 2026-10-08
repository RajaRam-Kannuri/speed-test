# syntax=docker/dockerfile:1
# Backend image: API, Celery worker and migrations. Build context: repository root.
# Based on the official Playwright image so Chromium, Firefox and WebKit are available to the worker.
FROM mcr.microsoft.com/playwright:v1.56.1-noble

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    LLX_RUNS_DIR=/tmp/llx-runs \
    LLX_STORAGE_LOCAL_ROOT=/data/artifacts

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/* && python3 -m venv /opt/venv

WORKDIR /app

# Playwright TypeScript engine
COPY engine/package.json engine/package-lock.json engine/tsconfig.json engine/
RUN --mount=type=secret,id=extra_ca,required=false if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca SSL_CERT_FILE=/run/secrets/extra_ca; fi; cd engine && npm ci --no-audit --no-fund
COPY engine/src engine/src
RUN cd engine && npm run build

# Python dependencies (testgen provides boundary-value generation)
COPY backend/requirements.txt backend/requirements.txt
RUN --mount=type=secret,id=extra_ca,required=false if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca SSL_CERT_FILE=/run/secrets/extra_ca; fi; pip install --no-cache-dir -r backend/requirements.txt
COPY pyproject.toml README.md ./
COPY testgen testgen
RUN --mount=type=secret,id=extra_ca,required=false if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca SSL_CERT_FILE=/run/secrets/extra_ca; fi; pip install --no-cache-dir .

COPY backend backend
RUN mkdir -p /data/artifacts /tmp/llx-runs && chown -R pwuser:pwuser /data /tmp/llx-runs /app/engine
USER pwuser
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
