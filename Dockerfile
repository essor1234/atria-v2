FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv --no-cache-dir

# ── Layer 1: install deps (cached as long as lockfile doesn't change) ──────────
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Layer 2: install playwright browsers (slow; cached separately) ─────────────
RUN uv run playwright install --with-deps chromium 2>/dev/null || true

# ── Layer 3: pre-cache tiktoken encodings so container works offline ──────────
RUN uv run python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

# ── Layer 4: copy source and install the package itself ───────────────────────
COPY . .
RUN uv sync --frozen --no-dev

# ── Layer 5: pre-install every module's requirements.txt into shared venv ─────
# Mirrors atria.core.modules.deps.install_module_deps so the container is
# offline-safe and the first module call doesn't trigger an install. Stamp
# files match the runtime hash check, so registry load is a no-op.
RUN for req in /app/modules/*/requirements.txt; do \
        [ -f "$req" ] || continue; \
        echo "[modules] installing $req"; \
        uv pip install --python /app/.venv/bin/python -r "$req" || exit 1; \
        sha256sum "$req" | awk '{print $1}' > "$(dirname "$req")/.deps.sha256"; \
    done

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

ENTRYPOINT ["/bin/sh", "-c", "\
  mkdir -p /root/.atria && \
  printf '{\"model\":\"%s\",\"api_base_url\":\"%s\"}\\n' \
    \"${ATRIA_MODEL:-gpt-4o}\" \
    \"${ATRIA_API_BASE_URL:-https://api.openai.com/v1/chat/completions}\" \
    > /root/.atria/settings.json && \
  exec atria --host 0.0.0.0 --port 8080\
"]
