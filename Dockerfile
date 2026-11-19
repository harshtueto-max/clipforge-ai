# Stage 1: Build the React + Vite frontend from source
FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Production FastAPI + FFmpeg + Faster-Whisper + YuNet + Hindi/Devanagari runtime
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISABLE_SQLALCHEMY_CEXT_RUNTIME=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    CLIPFORGE_PUBLIC_CLOUD=1 \
    CLIPFORGE_HOST=0.0.0.0 \
    CLIPFORGE_PORT=7860 \
    CLIPFORGE_HOME=/tmp/clipforge \
    CLIPFORGE_MODELS_DIR=/app/models \
    PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    fonts-noto-core \
    fonts-dejavu-core \
    fonts-liberation \
    fontconfig \
    libsndfile1 \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    libxext6 \
    libxrender1 \
    libsm6 \
    ca-certificates \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages globally into /usr/local so any runtime UID (Vercel Firecracker, uid 1000, root) finds them
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY assets /app/assets
COPY backend /app/backend
COPY --from=frontend-builder /frontend/dist /app/frontend/dist

# Pre-warm OpenCV YuNet face detector and Whisper 'base' model inside world-readable /app/models
WORKDIR /app/backend
RUN mkdir -p /app/models /tmp/clipforge && python -c "\
from app import config, main; \
from app.services import transcription, vision; \
config.ensure_dirs(); \
vision.download_yunet(); \
transcription.download_model('base'); \
print('Preloaded Whisper base + YuNet and verified app.main import!')" \
    && chmod -R a+rX /app && chmod 1777 /tmp/clipforge

EXPOSE 7860
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
