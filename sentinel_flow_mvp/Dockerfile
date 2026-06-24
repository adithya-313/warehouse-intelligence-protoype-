FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Pre-bake the PubMedBERT model into the image to prevent runtime cold-start timeouts
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('NeuML/pubmedbert-base-embeddings', device='cpu')"

COPY . .

EXPOSE 8000