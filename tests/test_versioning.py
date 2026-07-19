import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bump_version.py"
SPEC = importlib.util.spec_from_file_location("release_version", SCRIPT_PATH)
assert SPEC and SPEC.loader
bump_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bump_version)


def write_project(root: Path, version: str = "0.9.2") -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "mac-messages-mcp"\n'
        f'version = "{version}"\nrequires-python = ">=3.10"\n',
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps({"name": "mac-messages-mcp", "version": version}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        'version = 1\nrevision = 3\nrequires-python = ">=3.10"\n\n'
        '[[package]]\nname = "mac-messages-mcp"\n'
        f'version = "{version}"\nsource = {{ virtual = "." }}\n',
        encoding="utf-8",
    )


def test_validate_versions_accepts_synchronized_metadata(tmp_path: Path) -> None:
    write_project(tmp_path)
    assert bump_version.validate_versions(tmp_path, expected="0.9.2") == "0.9.2"


def test_validate_versions_reports_mismatch(tmp_path: Path) -> None:
    write_project(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["version"] = "1.0.0"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(bump_version.VersionError, match="inconsistent"):
        bump_version.validate_versions(tmp_path)


def test_set_version_delegates_to_uv_and_syncs_manifest(tmp_path: Path) -> None:
    write_project(tmp_path)

    def fake_uv(command, *, cwd, check):
        assert command == ["uv", "version", "--bump", "major", "--no-sync"]
        assert cwd == tmp_path
        assert check is True
        write_project(tmp_path, "1.0.0")
        # Simulate uv updating only pyproject + lock; the script owns manifest sync.
        manifest = {"name": "mac-messages-mcp", "version": "0.9.2"}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        return subprocess.CompletedProcess(command, 0)

    with patch.object(
        bump_version.shutil, "which", return_value="/usr/bin/uv"
    ), patch.object(bump_version.subprocess, "run", side_effect=fake_uv):
        assert bump_version.set_version(tmp_path, "major") == "1.0.0"

    assert json.loads((tmp_path / "manifest.json").read_text())["version"] == "1.0.0"
    assert bump_version.validate_versions(tmp_path) == "1.0.0"


def test_set_version_rolls_back_all_files_on_failure(tmp_path: Path) -> None:
    write_project(tmp_path)
    before = {
        name: (tmp_path / name).read_bytes() for name in bump_version.VERSION_FILES
    }

    def failing_uv(command, *, cwd, check):
        (tmp_path / "pyproject.toml").write_text("broken")
        raise subprocess.CalledProcessError(1, command)

    with patch.object(
        bump_version.shutil, "which", return_value="/usr/bin/uv"
    ), patch.object(
        bump_version.subprocess, "run", side_effect=failing_uv
    ), pytest.raises(
        subprocess.CalledProcessError
    ):
        bump_version.set_version(tmp_path, "major")

    assert {
        name: (tmp_path / name).read_bytes() for name in bump_version.VERSION_FILES
    } == before


def test_main_requires_explicit_action(tmp_path: Path, capsys) -> None:
    write_project(tmp_path)
    assert bump_version.main(["--root", str(tmp_path)]) == 2
    assert "Provide major, minor, patch" in capsys.readouterr().err


def test_explicit_version_must_be_stable_semver(tmp_path: Path) -> None:
    write_project(tmp_path)
    with pytest.raises(bump_version.VersionError, match="stable X.Y.Z"):
        bump_version.set_version(tmp_path, "1.0.0rc1")
