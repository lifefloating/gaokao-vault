#!/usr/bin/env bash
set -euo pipefail

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Install project dependencies
uv sync

# Install Scrapling browser dependencies (Playwright chromium for stealth mode)
uv run scrapling install --force

# Install pre-commit hooks
uv run pre-commit install --install-hooks

# Set up local PostgreSQL database for development
if command -v psql &> /dev/null; then
    echo "Setting up gaokao_vault database..."
    psql -U postgres -c "CREATE DATABASE gaokao_vault;" 2>/dev/null || true
    echo "Database ready. Run 'gaokao-vault init-db' to create tables."
fi
