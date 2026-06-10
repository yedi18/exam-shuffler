FROM python:3.11-slim

# Install Poppler (needed by pdf2image)
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shuffle.py app.py ./

EXPOSE 8080

# 300s timeout — PDF processing can take ~30–60s for large exams
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "300", "--workers", "2", "app:app"]
