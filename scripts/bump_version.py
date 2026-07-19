#!/usr/bin/env python3
"""Synchronize project release versions using uv.

Usage:
    uv run python scripts/bump_version.py major
    uv run python scripts/bump_version.py minor
    uv run python scripts/bump_version.py patch
    uv run python scripts/bump_version.py 1.2.3
    uv run python scripts/bump_version.py --check [--expected 1.2.3]

The script intentionally does not commit, tag, or push. It delegates the canonical
project and lockfile update to ``uv version``, then synchronizes ``manifest.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

PROJECT_NAME = "mac-messages-mcp"
BUMP_KINDS = {"major", "minor", "patch"}
STABLE_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
VERSION_FILES = ("pyproject.toml", "uv.lock", "manifest.json")


class VersionError(RuntimeError):
    """Raised when version metadata is missing or inconsistent."""


def _read_string_assignment(line: str) -> tuple[str, str] | None:
    """Parse a simple quoted TOML assignment used by release metadata."""
    key, separator, raw_value = line.partition("=")
    if not separator:
        return None
    key = key.strip()
    raw_value = raw_value.strip()
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, str):
        return None
    return key, value


def _read_project_metadata(path: Path) -> tuple[str, str]:
    """Read project name/version without adding a Python 3.10 TOML dependency."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise VersionError(f"Required file not found: {path}") from exc

    in_project = False
    project_name = None
    project_version = None
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if not in_project or not line or line.startswith("#"):
            continue
        assignment = _read_string_assignment(line)
        if assignment is None:
            continue
        key, value = assignment
        if key == "name":
            project_name = value
        elif key == "version":
            project_version = value

    if project_name != PROJECT_NAME or project_version is None:
        raise VersionError(
            "pyproject.toml is missing the expected project name/version"
        )
    return project_name, project_version


def _read_lock_version(path: Path) -> str:
    """Read this project's package version from uv.lock."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise VersionError(f"Required file not found: {path}") from exc

    package_name = None
    package_version = None
    in_package = False
    for raw_line in lines:
        line = raw_line.strip()
        if line == "[[package]]":
            if package_name == PROJECT_NAME and package_version is not None:
                return package_version
            package_name = None
            package_version = None
            in_package = True
            continue
        if line.startswith("[["):
            if package_name == PROJECT_NAME and package_version is not None:
                return package_version
            in_package = False
            continue
        if not in_package or not line or line.startswith("#"):
            continue
        assignment = _read_string_assignment(line)
        if assignment is None:
            continue
        key, value = assignment
        if key == "name":
            package_name = value
        elif key == "version":
            package_version = value

    if package_name == PROJECT_NAME and package_version is not None:
        return package_version
    raise VersionError(f"uv.lock has no package entry for {PROJECT_NAME}")


def read_versions(root: Path) -> dict[str, str]:
    """Read the version from all release metadata files."""
    _, project_version = _read_project_metadata(root / "pyproject.toml")

    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VersionError(f"Required file not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise VersionError(f"Invalid JSON in {manifest_path}: {exc}") from exc
    manifest_version = manifest.get("version")
    if not isinstance(manifest_version, str):
        raise VersionError("manifest.json is missing a string version")

    lock_version = _read_lock_version(root / "uv.lock")

    return {
        "pyproject.toml": project_version,
        "uv.lock": lock_version,
        "manifest.json": manifest_version,
    }


def validate_versions(
    root: Path, *, expected: str | None = None, ignore_lock: bool = False
) -> str:
    """Return the synchronized version or raise VersionError."""
    versions = read_versions(root)
    compared = {
        name: version
        for name, version in versions.items()
        if not (ignore_lock and name == "uv.lock")
    }
    unique = set(compared.values())
    if len(unique) != 1:
        details = ", ".join(f"{name}={version}" for name, version in compared.items())
        raise VersionError(f"Version metadata is inconsistent: {details}")

    version = next(iter(unique))
    if expected is not None and version != expected:
        raise VersionError(f"Expected version {expected}, found {version}")
    return version


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    temporary.replace(path)


def sync_manifest(root: Path, version: str) -> None:
    path = root / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise VersionError(f"Cannot update {path}: {exc}") from exc
    manifest["version"] = version
    _atomic_write_json(path, manifest)


def _snapshot(root: Path, names: Iterable[str]) -> dict[Path, bytes | None]:
    snapshot: dict[Path, bytes | None] = {}
    for name in names:
        path = root / name
        snapshot[path] = path.read_bytes() if path.exists() else None
    return snapshot


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(content)


def set_version(root: Path, target: str, *, dry_run: bool = False) -> str:
    """Use uv to update pyproject.toml/uv.lock, then sync manifest.json."""
    if shutil.which("uv") is None:
        raise VersionError("uv is required but was not found on PATH")

    if target in BUMP_KINDS:
        version_args = ["--bump", target]
    elif STABLE_VERSION_RE.fullmatch(target):
        version_args = [target]
    else:
        raise VersionError(
            "Version target must be major, minor, patch, or a stable X.Y.Z version"
        )

    command = ["uv", "version", *version_args, "--no-sync"]
    if dry_run:
        command.append("--dry-run")
        subprocess.run(command, cwd=root, check=True)
        return validate_versions(root, ignore_lock=False)

    snapshot = _snapshot(root, VERSION_FILES)
    try:
        subprocess.run(command, cwd=root, check=True)
        pyproject_version = read_versions(root)["pyproject.toml"]
        sync_manifest(root, pyproject_version)
        return validate_versions(root, expected=pyproject_version)
    except (OSError, subprocess.CalledProcessError, VersionError):
        _restore(snapshot)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        help="major, minor, patch, or an explicit stable X.Y.Z version",
    )
    parser.add_argument(
        "--check", action="store_true", help="validate metadata without changing files"
    )
    parser.add_argument("--expected", help="require this exact version with --check")
    parser.add_argument(
        "--ignore-lock",
        action="store_true",
        help="ignore uv.lock during --check (intended only for pre-release CI)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show uv's proposed change without writing",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.check:
            if args.target or args.dry_run:
                raise VersionError(
                    "--check cannot be combined with a version target or --dry-run"
                )
            version = validate_versions(
                root, expected=args.expected, ignore_lock=args.ignore_lock
            )
            print(version)
            return 0

        if args.expected or args.ignore_lock:
            raise VersionError("--expected and --ignore-lock require --check")
        if not args.target:
            raise VersionError("Provide major, minor, patch, X.Y.Z, or --check")

        version = set_version(root, args.target, dry_run=args.dry_run)
        if not args.dry_run:
            print(f"Version synchronized at {version} ({', '.join(VERSION_FILES)})")
        return 0
    except VersionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(
            f"Error: uv version failed with exit code {exc.returncode}", file=sys.stderr
        )
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
