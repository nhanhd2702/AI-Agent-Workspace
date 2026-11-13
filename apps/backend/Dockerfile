FROM python:3.12-slim

WORKDIR /app

# Install system utilities & build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e .

# Copy application source code
COPY app ./app

# Set default environment variables
ENV WORKSPACE_DIR=/app/workspace \
    BACKEND_PORT=8765 \
    LOCAL_AUTH_TOKEN=dev-local-token \
    PYTHONUNBUFFERED=1

EXPOSE 8765

VOLUME ["/app/workspace"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8765/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
