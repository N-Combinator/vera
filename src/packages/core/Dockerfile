FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY vera/ ./vera/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV VERA_DEV=0

CMD ["uvicorn", "vera.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
