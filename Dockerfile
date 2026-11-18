FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISABLE_SQLALCHEMY_CEXT_RUNTIME=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    CLIPFORGE_PUBLIC_CLOUD=1 \
    CLIPFORGE_HOST=0.0.0.0 \
    CLIPFORGE_PORT=7860

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
    ca-certificates \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs Docker containers as non-root uid 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH="/home/user/.local/bin:${PATH}" \
    CLIPFORGE_HOME=/home/user/.clipforge

WORKDIR /app

COPY --chown=user:user backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --user -r /app/backend/requirements.txt

COPY --chown=user:user assets /app/assets
COPY --chown=user:user backend /app/backend
COPY --chown=user:user frontend/dist /app/frontend/dist

# Pre-warm built-in CC0 audio library, OpenCV YuNet face detector, and Whisper 'base' + 'small' models
WORKDIR /app/backend
RUN python -c "\
from app import config; \
from app.services import transcription, vision; \
config.ensure_dirs(); \
vision.download_yunet(); \
transcription.download_model('base'); \
transcription.download_model('small'); \
print('Preloaded Whisper base + small and YuNet!')"

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
