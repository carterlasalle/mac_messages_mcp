FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY mac_messages_mcp ./mac_messages_mcp

RUN uv sync --frozen --no-dev \
    && if python3 -c "import pip" 2>/dev/null; then python3 -m pip uninstall -y pip setuptools wheel; fi \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --home-dir /home/app app \
    && chown -R app:app /app

USER app

ENTRYPOINT ["uv", "run", "--no-dev", "mac-messages-mcp"]
