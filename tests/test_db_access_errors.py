# Copyright (c) 2023 Carter Lasalle
"""Regression tests retained from the production-hardening baseline."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

from mac_messages_mcp.messages import query_addressbook_db, query_messages_db


def test_query_messages_db_operational_error(tmp_path: Path):
    # A real file: query_messages_db checks Path(db_path).exists(), which only
    # consults os.path.exists on 3.14+, so patching that seam is version-fragile.
    db_file = tmp_path / "chat.db"
    db_file.write_bytes(b"")
    with (
        patch("mac_messages_mcp.messages._connect_sqlite_readonly") as mock_connect,
        patch(
            "mac_messages_mcp.messages.get_messages_db_path",
            return_value=str(db_file),
        ),
    ):
        mock_connect.side_effect = sqlite3.OperationalError("permission denied")

        result = query_messages_db("SELECT 1")

    assert "Cannot access Messages database" in result[0]["error"]


def test_query_addressbook_db_all_sources_fail(tmp_path: Path):
    # Real file + the path seam: candidates exist but every connection fails.
    db_file = tmp_path / "a.abcddb"
    db_file.write_bytes(b"")
    with (
        patch("mac_messages_mcp.messages._connect_sqlite_readonly") as mock_connect,
        patch(
            "mac_messages_mcp.messages._addressbook_db_paths",
            return_value=([str(db_file)], "*/AddressBook-v22.abcddb"),
        ),
    ):
        mock_connect.side_effect = sqlite3.OperationalError("permission denied")

        result = query_addressbook_db("SELECT 1")

    assert "Could not access any AddressBook databases" in result[0]["error"]
