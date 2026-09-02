#!/usr/bin/env python3
"""
Build script for the Mac Messages MCP Claude Desktop extension (.mcpb).

Vendors a `uv` binary into the bundle so the packaged extension runs on
machines that don't have `uv` installed, then runs `mcpb pack`.

Usage:
    python scripts/build_mcpb.py [--arch arm64|x86_64] [--uv-version X.Y.Z] [--no-bundle]
    python scripts/build_mcpb.py --help

Options:
    --arch         Target architecture (defaults to the host architecture).
    --uv-version   uv release to vendor (default: pinned known-good version).
    --no-bundle    Pack against the system `uv` without vendoring a binary.

The vendored `uv` binary is architecture specific, so build one .mcpb per
architecture you need to support. On first launch the bundled `uv` still
downloads Python and dependencies, so network access is required once.
"""

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# Pinned uv release for reproducible builds; override with --uv-version.
DEFAULT_UV_VERSION = "0.11.19"
UV_DOWNLOAD_PREFIX = "https://github.com/astral-sh/uv/releases/download/"
UV_DOWNLOAD_URL = UV_DOWNLOAD_PREFIX + "{version}/{asset}.tar.gz"

# Map architecture aliases to uv's macOS release asset names.
ARCH_ASSETS = {
    "arm64": "uv-aarch64-apple-darwin",
    "aarch64": "uv-aarch64-apple-darwin",
    "x86_64": "uv-x86_64-apple-darwin",
    "intel": "uv-x86_64-apple-darwin",
}

BIN_DIR = Path("bin")
MANIFEST_PATH = Path("manifest.json")
BUNDLED_COMMAND = "${__dirname}/bin/uv"


def print_help():
    """Print help information"""
    print(__doc__)
    sys.exit(0)


def resolve_asset(arch):
    """Map an architecture alias to uv's release asset name."""
    key = (arch or platform.machine()).lower()
    asset = ARCH_ASSETS.get(key)
    if asset is None:
        valid = ", ".join(sorted(set(ARCH_ASSETS)))
        print(f"Error: unsupported arch '{key}'. Choose from: {valid}")
        sys.exit(1)
    return asset


def _download(url):
    """Download a GitHub uv release URL and return the raw bytes."""
    if not url.startswith(UV_DOWNLOAD_PREFIX):
        raise ValueError(f"refusing to download untrusted URL: {url}")
    print(f"Downloading {url}")
    request = urllib.request.Request(url, method="GET")
    # fmt: off
    with urllib.request.urlopen(request) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return response.read()
    # fmt: on


def vendor_uv(asset, version):
    """Download, checksum-verify, and extract the uv binary into bin/uv."""
    url = UV_DOWNLOAD_URL.format(version=version, asset=asset)
    archive = _download(url)

    expected = _download(url + ".sha256").decode().split()[0]
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        print("Error: checksum mismatch for uv download")
        print(f"  expected: {expected}")
        print(f"  actual:   {actual}")
        sys.exit(1)
    print("Checksum verified")

    BIN_DIR.mkdir(exist_ok=True)
    uv_path = BIN_DIR / "uv"
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "uv.tar.gz"
        tar_path.write_bytes(archive)
        with tarfile.open(tar_path) as tar:
            source = tar.extractfile(f"{asset}/uv")
            uv_path.write_bytes(source.read())
    uv_path.chmod(0o755)
    print(f"Vendored uv {version} ({asset}) -> {uv_path}")


def mcpb_cli():
    """Return the command used to invoke the mcpb CLI."""
    if shutil.which("mcpb"):
        return ["mcpb"]
    return ["npx", "--yes", "@anthropic-ai/mcpb"]


def pack(bundle):
    """Run `mcpb pack`, temporarily pointing the manifest at the bundled uv.

    The tracked manifest.json is always restored afterwards so the default
    system-uv flow stays unchanged.
    """
    original = MANIFEST_PATH.read_text()
    try:
        if bundle:
            manifest = json.loads(original)
            manifest["server"]["mcp_config"]["command"] = BUNDLED_COMMAND
            MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
            print(f"manifest command -> {BUNDLED_COMMAND}")
        subprocess.run(mcpb_cli() + ["pack"], check=True)
    finally:
        MANIFEST_PATH.write_text(original)
        if bundle:
            print("Restored manifest.json")


def main():
    args = sys.argv[1:]
    if any(a in ("-h", "--help", "help") for a in args):
        print_help()

    arch = None
    uv_version = DEFAULT_UV_VERSION
    bundle = True

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--arch":
            i += 1
            if i >= len(args):
                print("Error: --arch requires a value")
                sys.exit(1)
            arch = args[i]
        elif arg == "--uv-version":
            i += 1
            if i >= len(args):
                print("Error: --uv-version requires a value")
                sys.exit(1)
            uv_version = args[i]
        elif arg == "--no-bundle":
            bundle = False
        else:
            print(f"Error: unknown argument '{arg}'")
            print(
                "Usage: python scripts/build_mcpb.py [--arch arm64|x86_64] "
                "[--uv-version X.Y.Z] [--no-bundle]"
            )
            sys.exit(1)
        i += 1

    if sys.platform != "darwin":
        print("Warning: mac-messages-mcp targets macOS; building on a non-macOS host.")

    if bundle:
        asset = resolve_asset(arch)
        vendor_uv(asset, uv_version)
    else:
        print("Packing against system uv (no vendored binary).")

    pack(bundle)
    print("Done.")


if __name__ == "__main__":
    main()
