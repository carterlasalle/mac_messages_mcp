"""Regression tests retained from the production-hardening baseline."""

import sqlite3
from unittest.mock import patch

from mac_messages_mcp.messages import query_addressbook_db, query_messages_db


@patch("mac_messages_mcp.messages._connect_sqlite_readonly")
@patch("mac_messages_mcp.messages.os.path.exists", return_value=True)
@patch("mac_messages_mcp.messages.get_messages_db_path", return_value="/tmp/chat.db")
def test_query_messages_db_operational_error(_path, _exists, mock_connect):
    mock_connect.side_effect = sqlite3.OperationalError("permission denied")

    result = query_messages_db("SELECT 1")

    assert "Cannot access Messages database" in result[0]["error"]


@patch("mac_messages_mcp.messages._connect_sqlite_readonly")
@patch("mac_messages_mcp.messages.glob.glob", return_value=["/tmp/a.abcddb"])
@patch("mac_messages_mcp.messages.os.path.exists", return_value=False)
def test_query_addressbook_db_all_sources_fail(_exists, _glob, mock_connect):
    mock_connect.side_effect = sqlite3.OperationalError("permission denied")

    result = query_addressbook_db("SELECT 1")

    assert "Could not access any AddressBook databases" in result[0]["error"]
