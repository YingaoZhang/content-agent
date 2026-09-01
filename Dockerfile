FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

COPY app ./app
COPY frontend ./frontend
COPY vendor ./vendor
COPY api_server.py README.md .env.example ./

RUN mkdir -p /app/storage/jobs /app/storage/uploads

EXPOSE 8000

CMD [".venv/bin/python", "-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
