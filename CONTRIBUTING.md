# Contributing

## Setup

```bash
uv sync --frozen --extra dev
```

## Checks

```bash
uv run pytest
uv run black --check .
uv run isort --check-only .
uv run mypy --follow-imports=skip --disable-error-code no-any-return mac_messages_mcp/server.py
uv build
yarn global add @anthropic-ai/mcpb@2.1.2
python scripts/build_mcpb.py --arch arm64
python scripts/build_mcpb.py --arch x86_64
```

Tests must not access a contributor's real Messages or Contacts data. Use temporary SQLite fixtures and mock AppleScript execution. Never commit database copies, phone numbers, contact exports, messages, or attachments.

Keep pull requests focused and document user impact, privacy implications, macOS/Python versions tested, and the commands used for validation.
