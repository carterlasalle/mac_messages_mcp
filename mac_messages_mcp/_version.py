# Copyright (c) 2023 Carter Lasalle
"""Installed version of the mac-messages-mcp package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mac-messages-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
