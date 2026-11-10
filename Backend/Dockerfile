FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

# Install dependencies first to leverage layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent volume for SQLite
VOLUME ["/app/data"]
ENV DB_PATH=/app/data/facturas.db
ENV INVOICES_DIR=/app/facturas

CMD ["python", "-m", "agent.main"]
