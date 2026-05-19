# syntax=docker/dockerfile:1.4
# CFIS Dockerfile v3 — Cache-first. Arabic OCR models in named volume.
# Models download ONCE via model_init service. Never during build.
# Previous: python:3.11-slim (now 3.10-slim for PaddlePaddle 2.6 compatibility)

FROM python:3.10-slim AS base

# System packages — cached layer
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      libglib2.0-0 libsm6 libxrender1 libxext6 libgomp1 \
      poppler-utils libpoppler-dev curl wget build-essential git \
      libgl1 libglib2.0-0 \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies — cached layer
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# PaddleOCR model path — lives in Docker named volume, not image
ENV PADDLEOCR_HOME=/root/.paddleocr
ENV PADDLE_MODEL_DIR=/root/.paddleocr
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# GPU memory limit (harmless if CPU-only)
ENV FLAGS_fraction_of_gpu_memory_to_use=0.4
# Force CPU — set CUDA_VISIBLE_DEVICES="" to prevent GPU segfault when CUDA unavailable
ENV CUDA_VISIBLE_DEVICES=-1

FROM base AS app
WORKDIR /app
COPY . .

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
  CMD curl -sf http://localhost:8000/health | python3 -c \
    "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('status')=='ok' else 1)"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--log-level", "info"]
