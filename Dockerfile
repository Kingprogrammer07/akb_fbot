# -----------------------------
# Stage 1: Build dependencies
# -----------------------------
FROM python:3.12.5-slim AS builder

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=2.1.3

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry via official installer
RUN curl -sSL https://install.python-poetry.org  | POETRY_HOME=/opt/poetry python3 - --version ${POETRY_VERSION}

ENV PATH="/opt/poetry/bin:${PATH}"

# Copy only dependency files
COPY pyproject.toml poetry.lock /app/

# Install production dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

# -----------------------------
# Stage 2: Final image
# -----------------------------
FROM python:3.12.5-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    postgresql-client \
    redis-tools \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy installed dependencies from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . /app

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Entrypoint
ENTRYPOINT ["./entrypoint.sh"]
