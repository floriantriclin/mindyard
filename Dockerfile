# mindyard: one container serving the vaults under /data over MCP (HTTP).
FROM python:3.12-slim

# git: every write_batch is a commit. ripgrep: fast search (a Python scan otherwise).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies in their own layer, replayed from the lockfile without resolving.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH" \
    MINDYARD_DATA_ROOT=/data \
    MINDYARD_HOST=0.0.0.0 \
    MINDYARD_PORT=8787

# No default auth: with MINDYARD_AUTH unset (none), the server refuses to bind
# 0.0.0.0 and exits. Pick bearer or google in the environment.
EXPOSE 8787
VOLUME ["/data"]
CMD ["mindyard", "serve"]
