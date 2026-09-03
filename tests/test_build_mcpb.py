import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_mcpb.py"
SPEC = importlib.util.spec_from_file_location("build_mcpb", SCRIPT_PATH)
assert SPEC and SPEC.loader
build_mcpb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_mcpb)


def _https_response(status, body=b"", location=None):
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.getheader.side_effect = lambda name: (
        location if name == "Location" else None
    )
    return response


def test_download_rejects_non_release_url():
    with pytest.raises(ValueError, match="untrusted URL"):
        build_mcpb._download("https://evil.example/payload")


def test_download_allows_pinned_uv_release_url():
    url = build_mcpb.UV_DOWNLOAD_URL.format(
        version=build_mcpb.DEFAULT_UV_VERSION,
        asset="uv-aarch64-apple-darwin",
    )
    connection = MagicMock()
    connection.getresponse.return_value = _https_response(200, b"uv")
    with patch.object(
        build_mcpb.http.client, "HTTPSConnection", return_value=connection
    ) as mock_conn:
        assert build_mcpb._download(url) == b"uv"
        mock_conn.assert_called_once()
        assert mock_conn.call_args[0][0] == "github.com"
        connection.request.assert_called_once()
        method, path = connection.request.call_args[0][:2]
        assert method == "GET"
        assert path.startswith("/astral-sh/uv/releases/download/")


def test_download_follows_allowlisted_redirect():
    url = build_mcpb.UV_DOWNLOAD_URL.format(
        version=build_mcpb.DEFAULT_UV_VERSION,
        asset="uv-aarch64-apple-darwin",
    )
    github = MagicMock()
    github.getresponse.return_value = _https_response(
        302,
        location="https://objects.githubusercontent.com/uv.tar.gz",
    )
    objects = MagicMock()
    objects.getresponse.return_value = _https_response(200, b"uv-bytes")

    def _connect(host, timeout=None):
        return github if host == "github.com" else objects

    with patch.object(build_mcpb.http.client, "HTTPSConnection", side_effect=_connect):
        assert build_mcpb._download(url) == b"uv-bytes"
    objects.request.assert_called_once()
    assert objects.request.call_args[0][1] == "/uv.tar.gz"


def test_download_refuses_redirect_off_github():
    url = build_mcpb.UV_DOWNLOAD_URL.format(
        version=build_mcpb.DEFAULT_UV_VERSION,
        asset="uv-aarch64-apple-darwin",
    )
    connection = MagicMock()
    connection.getresponse.return_value = _https_response(
        302, location="https://evil.example/payload"
    )
    with patch.object(
        build_mcpb.http.client, "HTTPSConnection", return_value=connection
    ):
        with pytest.raises(ValueError, match="untrusted URL"):
            build_mcpb._download(url)
