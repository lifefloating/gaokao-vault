# ---------- build stage ----------
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Build deps for asyncpg and quickjs (C extensions need headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc libc-dev make \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer cache)
COPY uv.lock pyproject.toml /app/
RUN uv sync --frozen --no-install-project

# Copy source and install project
COPY . /app
RUN uv sync --frozen

# Install Scrapling browser dependencies (Playwright chromium etc.)
RUN uv run scrapling install --force

# ---------- runtime stage ----------
FROM python:3.12-slim

# System deps: Playwright/Chromium libs + libpq for asyncpg + PostgreSQL client for debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 postgresql-client \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libatspi2.0-0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app

# Make the CLI available
ENV PATH="/app/.venv/bin:$PATH"

# Default: show help
ENTRYPOINT ["gaokao-vault"]
CMD ["--help"]
