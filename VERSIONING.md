# Versioning and releases

Mac Messages MCP follows semantic versioning (`MAJOR.MINOR.PATCH`). The package,
lockfile, Claude Desktop extension manifest, Git tag, PyPI release, and GitHub
release must all agree on the same version.

## Bump a version

Use the repository's UV-backed version command:

```bash
uv run python scripts/bump_version.py major
uv run python scripts/bump_version.py minor
uv run python scripts/bump_version.py patch
```

An explicit stable version is also supported:

```bash
uv run python scripts/bump_version.py 1.2.3
```

The command is deliberately non-interactive. It:

1. Runs `uv version`, which updates `pyproject.toml` and `uv.lock` together.
2. Synchronizes the Claude Desktop extension version in `manifest.json`.
3. Verifies that all three files contain the same stable version.
4. Rolls every file back if any part of the update fails.

It does **not** commit, tag, push, or publish. Those are separate reviewable
operations.

Preview a change without writing files:

```bash
uv run python scripts/bump_version.py major --dry-run
```

Validate the current repository metadata:

```bash
uv run python scripts/bump_version.py --check
```

## Release process

1. Run the version command.
2. Add the new release section to `CHANGELOG.md`.
3. Open and merge a release pull request after CI is green.

A merge to `main` that changes `pyproject.toml` or `manifest.json` starts the
trusted release workflow. The workflow then:

1. Synchronizes and commits `uv.lock` if the release branch did not include the
   generated lockfile change.
2. Re-validates version metadata and runs tests, formatting, typing, build, and
   clean-wheel installation checks.
3. Publishes to PyPI using OIDC trusted publishing; no long-lived PyPI token is
   stored in GitHub.
4. Creates an annotated `vX.Y.Z` tag only after PyPI succeeds.
5. Creates or updates the matching GitHub release using the version's changelog
   section.

Publishing is idempotent: rerunning the workflow skips files already present on
PyPI and repairs a missing tag or GitHub release.

## Version authority

- `pyproject.toml` is the canonical project version during development.
- `uv.lock` is synchronized by `uv version`.
- `manifest.json` mirrors the version for MCPB packaging.
- `mac_messages_mcp.__version__` reads the installed package metadata at runtime.
- `vX.Y.Z` tags and GitHub releases are created by the trusted release workflow.

## Choosing a bump

- **PATCH**: backward-compatible fixes.
- **MINOR**: backward-compatible features and meaningful improvements.
- **MAJOR**: a compatibility break or a new stability contract, such as the
  first stable `1.0.0` release.
