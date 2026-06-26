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

# 2. ISOLATED AI LAYER: Install CPU-only PyTorch and sentence-transformers.
# We use a 1000s timeout and BuildKit cache to survive slow/dropping internet.
# Pulling the CPU version saves ~650MB of download size.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=1000 torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --default-timeout=1000 sentence-transformers==2.5.1

# 3. ISOLATED MODEL LAYER: Download the 400MB model.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('NeuML/pubmedbert-base-embeddings', device='cpu')"

# 4. DEPENDENCY LAYER: Copy requirements and install the rest.
COPY requirements.txt .

# Use the 1000s timeout here as well
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=1000 -r requirements.txt

# 5. APPLICATION LAYER
COPY . .

EXPOSE 8000
