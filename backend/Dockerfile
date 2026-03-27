FROM python:3.13-slim

WORKDIR /app/backend

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code + monorepo context needed for architecture indexing
COPY backend /app/backend
COPY frontend /app/frontend
COPY packages /app/packages
COPY docs /app/docs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
