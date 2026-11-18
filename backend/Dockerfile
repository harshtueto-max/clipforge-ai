FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISABLE_SQLALCHEMY_CEXT_RUNTIME=1 \
    CLIPFORGE_HOST=0.0.0.0 \
    CLIPFORGE_PORT=8765

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-indic \
    fonts-dejavu-core \
    libsndfile1 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY assets /app/assets
COPY backend /app/backend

EXPOSE 8765
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8765}"]
