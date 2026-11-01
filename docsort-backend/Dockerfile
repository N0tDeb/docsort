# DocSort backend — FastAPI + OCR
FROM python:3.15-slim

# System dependencies: Tesseract OCR with Marathi + Hindi language data
# (English ships by default). Needed for the document-reading pipeline.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-mar \
        tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer caches unless requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
RUN addgroup --system docsort && adduser --system --ingroup docsort --home /home/docsort docsort
COPY --chown=docsort:docsort app ./app

USER docsort

EXPOSE 8000

# Secrets (JWT_SECRET, Supabase, Gemini keys) are supplied at runtime, e.g.:
#   docker run --env-file .env -p 8000:8000 docsort-backend
# The server refuses to start without Supabase credentials and JWT_SECRET.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Container-level liveness check without adding curl/wget to the image.
# Deployment orchestrators should use GET /ready separately for dependency-aware readiness.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=2)" || exit 1
