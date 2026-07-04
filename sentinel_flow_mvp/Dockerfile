# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# ISOLATED AI LAYER: Permanent cache for heavy ML libraries
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install sentence-transformers==2.5.1

# ISOLATED MODEL LAYER: Pre-bake the 400MB embedding model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('NeuML/pubmedbert-base-embeddings', device='cpu')"

# DEPENDENCY LAYER
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# APPLICATION LAYER
COPY . .

EXPOSE 8000
