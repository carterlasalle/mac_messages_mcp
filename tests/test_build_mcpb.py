import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_mcpb.py"
SPEC = importlib.util.spec_from_file_location("build_mcpb", SCRIPT_PATH)
assert SPEC and SPEC.loader
build_mcpb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_mcpb)


def test_download_rejects_non_release_url():
    with pytest.raises(ValueError, match="untrusted URL"):
        build_mcpb._download("https://evil.example/payload")


def test_download_allows_pinned_uv_release_url():
    url = build_mcpb.UV_DOWNLOAD_URL.format(
        version=build_mcpb.DEFAULT_UV_VERSION,
        asset="uv-aarch64-apple-darwin",
    )
    with patch.object(build_mcpb.urllib.request, "urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = b"uv"
        assert build_mcpb._download(url) == b"uv"
        mock_open.assert_called_once()
        request = mock_open.call_args[0][0]
        assert request.full_url.startswith(build_mcpb.UV_DOWNLOAD_PREFIX)
