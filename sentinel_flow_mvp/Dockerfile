# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# 1. Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 2. ISOLATED AI LAYER: Install sentence-transformers first.
# By doing this before requirements.txt, this layer caches permanently.
RUN pip install --no-cache-dir sentence-transformers==2.5.1

# 3. ISOLATED MODEL LAYER: Download the 400MB model.
# This will now NEVER re-download even if requirements.txt changes.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('NeuML/pubmedbert-base-embeddings', device='cpu')"

# 4. DEPENDENCY LAYER: Copy requirements and install the rest.
COPY requirements.txt .

# 5. BUILDKIT CACHE: If the network drops, pip will resume from the local cache instead of starting from zero.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 6. APPLICATION LAYER: Copy the frequently changing source code last.
COPY . .

EXPOSE 8000
