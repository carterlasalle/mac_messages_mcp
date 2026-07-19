"""
Tests for the messages module
"""

import os
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from mac_messages_mcp.messages import (
    _connect_sqlite_readonly,
    _find_chat_by_identifier,
    _format_phone_for_messages,
    _sanitize_message_body,
    _send_message_to_recipient,
    escape_applescript,
    extract_body_from_attributed,
    find_contact_by_name,
    get_chat_mapping,
    get_messages_db_path,
    get_recent_messages,
    query_addressbook_db,
    query_messages_db,
    run_applescript,
    send_message,
)


class TestMessages(unittest.TestCase):
    """Tests for the messages module"""

    @patch("subprocess.Popen")
    def test_run_applescript_success(self, mock_popen):
        """Test running AppleScript successfully"""
        # Setup mock
        process_mock = MagicMock()
        process_mock.returncode = 0
        process_mock.communicate.return_value = (b"Success", b"")
        mock_popen.return_value = process_mock

        # Run function
        result = run_applescript('tell application "Messages" to get name')

        # Check results
        self.assertEqual(result, "Success")
        mock_popen.assert_called_with(
            ["osascript", "-e", 'tell application "Messages" to get name'],
            stdout=-1,
            stderr=-1,
        )
        process_mock.communicate.assert_called_once_with(timeout=30)

    @patch("subprocess.Popen")
    def test_run_applescript_error(self, mock_popen):
        """Test running AppleScript with error"""
        # Setup mock
        process_mock = MagicMock()
        process_mock.returncode = 1
        process_mock.communicate.return_value = (b"", b"Error message")
        mock_popen.return_value = process_mock

        # Run function
        result = run_applescript("invalid script")

        # Check results
        self.assertEqual(result, "Error: Error message")

    @patch("subprocess.Popen")
    def test_run_applescript_timeout_kills_process(self, mock_popen):
        process_mock = MagicMock()
        process_mock.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="osascript", timeout=1),
            (b"", b""),
        ]
        mock_popen.return_value = process_mock

        result = run_applescript("delay 10", timeout=1)

        self.assertEqual(result, "Error: AppleScript timed out after 1 seconds")
        process_mock.kill.assert_called_once_with()

    def test_readonly_connection_rejects_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "messages.db")
            writable = sqlite3.connect(db_path)
            writable.execute("CREATE TABLE message (id INTEGER)")
            writable.commit()
            writable.close()

            connection = _connect_sqlite_readonly(db_path)
            self.assertEqual(
                connection.execute("SELECT name FROM sqlite_master").fetchone()[0],
                "message",
            )
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO message VALUES (1)")
            connection.close()

    @patch("mac_messages_mcp.messages._connect_sqlite_readonly")
    @patch("mac_messages_mcp.messages.os.path.exists", return_value=True)
    @patch(
        "mac_messages_mcp.messages.get_messages_db_path", return_value="/tmp/chat.db"
    )
    def test_query_messages_db_operational_error(self, _path, _exists, mock_connect):
        mock_connect.side_effect = sqlite3.OperationalError("permission denied")

        result = query_messages_db("SELECT 1")

        self.assertIn("Cannot access Messages database", result[0]["error"])

    @patch("mac_messages_mcp.messages._connect_sqlite_readonly")
    @patch("mac_messages_mcp.messages.glob.glob", return_value=["/tmp/a.abcddb"])
    @patch("mac_messages_mcp.messages.os.path.exists", return_value=False)
    def test_query_addressbook_db_all_sources_fail(self, _exists, _glob, mock_connect):
        mock_connect.side_effect = sqlite3.OperationalError("permission denied")

        result = query_addressbook_db("SELECT 1")

        self.assertIn("Could not access any AddressBook databases", result[0]["error"])

    @patch("os.path.expanduser")
    def test_get_messages_db_path(self, mock_expanduser):
        """Test getting the Messages database path"""
        # Setup mock
        mock_expanduser.return_value = "/Users/testuser"

        # Run function
        result = get_messages_db_path()

        # Check results
        self.assertEqual(result, "/Users/testuser/Library/Messages/chat.db")
        mock_expanduser.assert_called_with("~")


class TestEscapeAppleScriptInjection(unittest.TestCase):
    """Tests for AppleScript escaping injection edge cases."""

    def test_plain_text_unchanged(self):
        """Test that plain text passes through unchanged"""
        # Run function
        result = escape_applescript("hello world")

        # Check results
        self.assertEqual(result, "hello world")

    def test_quotes_escaped(self):
        """Test that double quotes are escaped"""
        # Run function
        result = escape_applescript('say "hello"')

        # Check results
        self.assertEqual(result, 'say \\"hello\\"')

    def test_backslashes_escaped(self):
        """Test that backslashes are escaped"""
        # Run function
        result = escape_applescript("path\\to\\file")

        # Check results
        self.assertEqual(result, "path\\\\to\\\\file")

    def test_escape_order_prevents_injection(self):
        """Test that backslashes are escaped before quotes to prevent injection"""
        # Setup - a string with backslash-quote that could break AppleScript if
        # quotes are escaped first (producing \\" which unescapes the quote)
        malicious = 'test\\"injection'

        # Run function
        result = escape_applescript(malicious)

        # Check results - backslash escaped first, then quote
        # Input:  test\"injection
        # Step 1: test\\"injection  (backslash escaped)
        # Step 2: test\\\\"injection  (quote escaped)
        self.assertEqual(result, 'test\\\\\\"injection')
        # The result should NOT contain an unescaped quote
        self.assertNotIn('\\"', result.replace('\\\\"', ""))

    def test_empty_string(self):
        """Test that empty string returns empty string"""
        # Run function
        result = escape_applescript("")

        # Check results
        self.assertEqual(result, "")

    def test_unicode_unchanged(self):
        """Test that unicode characters pass through unchanged"""
        # Run function
        result = escape_applescript("Hello 世界")

        # Check results
        self.assertEqual(result, "Hello 世界")


class TestSanitizeMessageBody(unittest.TestCase):
    """Tests for MCP-safe message rendering."""

    def test_control_characters_are_removed(self):
        self.assertEqual(_sanitize_message_body("hello\x00there\x07"), "hello there ")

    def test_newlines_are_rendered_inline(self):
        self.assertEqual(_sanitize_message_body("line 1\nline 2"), "line 1\\nline 2")

    def test_long_messages_are_truncated(self):
        result = _sanitize_message_body("abcdef", max_chars=3)
        self.assertEqual(result, "abc... [truncated 3 chars]")


class TestSendMessageToRecipient(unittest.TestCase):
    """Tests for _send_message_to_recipient escaping"""

    @patch("mac_messages_mcp.messages.run_applescript")
    def test_does_not_raise_name_error(self, mock_applescript):
        """Test that safe_recipient is defined (was NameError after merge)"""
        from mac_messages_mcp.messages import _send_message_to_recipient

        # Setup mock
        mock_applescript.return_value = "Success"

        # Run function — this raised NameError before the fix
        result = _send_message_to_recipient("+15551234567", "hello")

        # Check results
        self.assertIn("sent successfully", result)

    @patch("mac_messages_mcp.messages.run_applescript")
    def test_recipient_with_quotes_is_escaped(self, mock_applescript):
        """Test that quotes in recipient don't break the AppleScript command"""
        from mac_messages_mcp.messages import _send_message_to_recipient

        # Setup mock
        mock_applescript.return_value = "Success"

        # Run function with a recipient containing quotes
        _send_message_to_recipient('+1234"567', "hello")

        # Check results — the AppleScript command should have escaped quotes
        call_args = mock_applescript.call_args[0][0]
        self.assertIn('+1234\\"567', call_args)
        self.assertNotIn('"+1234"567"', call_args)


class TestRecipientNormalization(unittest.TestCase):
    """Tests for recipient formats handed to Messages.app."""

    def test_phone_formatter_preserves_e164_plus(self):
        self.assertEqual(_format_phone_for_messages("+19565179045"), "+19565179045")

    def test_phone_formatter_adds_plus_to_country_code_digits(self):
        self.assertEqual(_format_phone_for_messages("19565179045"), "+19565179045")

    def test_phone_formatter_assumes_us_country_code_for_ten_digits(self):
        self.assertEqual(_format_phone_for_messages("(956) 517-9045"), "+19565179045")

    @patch("mac_messages_mcp.messages._send_message_to_recipient")
    def test_send_message_normalizes_bare_digits_before_dispatch(self, mock_send):
        mock_send.return_value = "sent"

        result = send_message("19565179045", "hello")

        self.assertEqual(result, "sent")
        mock_send.assert_called_once_with("+19565179045", "hello", group_chat=False)

    @patch("mac_messages_mcp.messages._send_message_to_recipient")
    def test_send_message_rejects_short_phone_numbers(self, mock_send):
        result = send_message("12345", "hello")

        self.assertIn("Phone recipients must be E.164-style", result)
        mock_send.assert_not_called()

    @patch("mac_messages_mcp.messages.get_cached_contacts")
    def test_find_contact_returns_messages_ready_phone_number(self, mock_contacts):
        mock_contacts.return_value = {"19565179045": "Hugo Example"}
        with patch.dict(
            "mac_messages_mcp.messages._PHONE_TO_DETAILS_MAP",
            {
                "19565179045": {
                    "first_name": "Hugo",
                    "last_name": "Example",
                    "nickname": "",
                    "full_name": "Hugo Example",
                }
            },
            clear=True,
        ):
            matches = find_contact_by_name("Hugo")

        self.assertEqual(matches[0]["phone"], "+19565179045")


class TestTempFileRace(unittest.TestCase):
    """Tests for temp file race condition fix in _send_message_to_recipient"""

    @patch("mac_messages_mcp.messages.run_applescript")
    def test_temp_file_uses_unique_name(self, mock_applescript):
        """Test that temp file gets a unique name (not hardcoded imessage_tmp.txt)"""
        import os

        mock_applescript.return_value = ""

        # Run function
        _send_message_to_recipient("+15551234567", "test message")

        # Check results - the AppleScript should reference a temp file path
        script = mock_applescript.call_args[0][0]
        # Should NOT use the old hardcoded name
        self.assertNotIn("imessage_tmp.txt", script)
        # Should reference a temp directory path
        self.assertTrue(
            "/tmp/" in script or "/var/folders/" in script,
            f"Expected temp directory path in script, got: {script[:200]}",
        )

    @patch("mac_messages_mcp.messages.run_applescript")
    def test_temp_file_cleaned_up_on_success(self, mock_applescript):
        """Test that temp file is removed after successful send"""
        import glob
        import os

        mock_applescript.return_value = ""

        # Count temp files before
        before = set(glob.glob("/tmp/tmp*.txt"))

        # Run function
        _send_message_to_recipient("+15551234567", "test message")

        # Count temp files after - should not have leaked
        after = set(glob.glob("/tmp/tmp*.txt"))
        leaked = after - before
        self.assertEqual(len(leaked), 0, f"Temp files leaked: {leaked}")

    @patch("mac_messages_mcp.messages.run_applescript")
    def test_temp_file_cleaned_up_on_error(self, mock_applescript):
        """Test that temp file is removed even when AppleScript fails"""
        import glob
        import os

        mock_applescript.return_value = "Error: some failure"

        # Count temp files before
        before = set(glob.glob("/tmp/tmp*.txt"))

        # Run function (will fall back to _send_message_direct which also uses applescript)
        _send_message_to_recipient("+15551234567", "test message")

        # Count temp files after
        after = set(glob.glob("/tmp/tmp*.txt"))
        leaked = after - before
        self.assertEqual(len(leaked), 0, f"Temp files leaked: {leaked}")


class TestGetChatMapping(unittest.TestCase):
    """Tests for get_chat_mapping error handling"""

    @patch("mac_messages_mcp.messages.get_messages_db_path")
    def test_returns_mapping(self, mock_path):
        """Test happy path returns dict of room_name -> display_name"""
        # Setup - create a temp DB with the expected schema
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            mock_path.return_value = db_path
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE chat (room_name TEXT, display_name TEXT)")
            conn.execute("INSERT INTO chat VALUES ('room1', 'Alice')")
            conn.execute("INSERT INTO chat VALUES ('room2', 'Bob')")
            conn.commit()
            conn.close()

            # Run function
            result = get_chat_mapping()

            # Check results
            self.assertEqual(result, {"room1": "Alice", "room2": "Bob"})
        finally:
            os.unlink(db_path)

    @patch("mac_messages_mcp.messages.get_messages_db_path")
    def test_inaccessible_db_returns_empty_dict(self, mock_path):
        """Test that inaccessible database returns empty dict instead of crashing"""
        # Setup
        mock_path.return_value = "/nonexistent/path/chat.db"

        # Run function
        result = get_chat_mapping()

        # Check results
        self.assertEqual(result, {})

    @patch("mac_messages_mcp.messages.get_messages_db_path")
    def test_empty_table_returns_empty_dict(self, mock_path):
        """Test that empty chat table returns empty dict"""
        # Setup
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            mock_path.return_value = db_path
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE chat (room_name TEXT, display_name TEXT)")
            conn.commit()
            conn.close()

            # Run function
            result = get_chat_mapping()

            # Check results
            self.assertEqual(result, {})
        finally:
            os.unlink(db_path)


class TestGetRecentMessagesChatFilter(unittest.TestCase):
    """Tests for group chat filtering in get_recent_messages."""

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_find_chat_by_identifier_accepts_short_chat_id(self, mock_query):
        mock_query.return_value = [
            {
                "ROWID": 7,
                "display_name": "Family",
                "chat_identifier": "iMessage;-;chat123",
                "room_name": "chat123",
            }
        ]

        result = _find_chat_by_identifier("chat123")

        self.assertEqual(result["ROWID"], 7)
        params = mock_query.call_args[0][1]
        self.assertIn("chat123", params)
        self.assertIn("iMessage;-;chat123", params)

    @patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
    @patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Alice")
    @patch(
        "mac_messages_mcp.messages._find_chat_by_identifier",
        return_value={"ROWID": 7, "display_name": "Family"},
    )
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_get_recent_messages_filters_by_chat_id(
        self, mock_query, _chat, _name, _mapping, _atts
    ):
        mock_query.return_value = [
            {
                "ROWID": 100,
                "date": 700_000_000_000_000_000,
                "text": "group hello",
                "attributedBody": None,
                "is_from_me": 0,
                "handle_id": 99,
                "cache_roomnames": None,
            }
        ]

        result = get_recent_messages(hours=24, chat_id="chat123")

        sql, params = mock_query.call_args[0]
        self.assertIn("chat_message_join", sql)
        self.assertEqual(params[-1], 7)
        self.assertIn("[Family]", result)
        self.assertIn("group hello", result)

    def test_get_recent_messages_rejects_contact_and_chat_id(self):
        result = get_recent_messages(hours=24, contact="Alice", chat_id="chat123")

        self.assertIn("either contact or chat_id", result)


class TestTimestampConversion(unittest.TestCase):
    """Tests for Apple epoch timestamp conversion"""

    def test_apple_epoch_constant(self):
        """Test that 978307200 is the correct offset between Unix and Apple epochs"""
        from datetime import datetime, timezone

        # Setup
        unix_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        apple_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)

        # Run
        delta_seconds = int((apple_epoch - unix_epoch).total_seconds())

        # Check results
        self.assertEqual(delta_seconds, 978307200)

    def test_nanosecond_timestamp_conversion(self):
        """Test converting a nanosecond Apple timestamp to a datetime"""
        from datetime import datetime, timezone

        # Setup - a known Apple timestamp in nanoseconds
        # 2025-01-01 00:00:00 UTC = 757382400 seconds after Apple epoch
        apple_epoch_offset = 978307200
        apple_seconds = 757382400
        apple_nanos = apple_seconds * 1_000_000_000

        # Run - convert like the fixed code does
        msg_timestamp_s = apple_nanos / 1_000_000_000
        date_val = datetime.fromtimestamp(
            msg_timestamp_s + apple_epoch_offset, tz=timezone.utc
        )

        # Check results
        expected = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(date_val, expected)

    def test_second_format_timestamp(self):
        """Test converting a second-format Apple timestamp"""
        from datetime import datetime, timezone

        # Setup - timestamp already in seconds (len <= 10)
        apple_epoch_offset = 978307200
        apple_seconds = 757382400  # 2025-01-01 00:00:00 UTC

        # Run
        msg_timestamp_s = apple_seconds  # already in seconds, no division needed
        date_val = datetime.fromtimestamp(
            msg_timestamp_s + apple_epoch_offset, tz=timezone.utc
        )

        # Check results
        expected = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(date_val, expected)


class TestExtractBodyFromAttributed(unittest.TestCase):
    """Tests for extract_body_from_attributed"""

    def _build_blob(self, text):
        """Build a minimal typedstream blob with the given text content"""
        encoded = text.encode("utf-8")
        length = len(encoded)
        # NSString marker + 5-byte header (\x01\x00\x84\x01+) + length byte + text
        if length < 0x80:
            length_bytes = bytes([length])
        else:
            # 0x81 prefix for 2-byte LE length
            length_bytes = b"\x81" + length.to_bytes(2, "little")
        return (
            b"prefix"
            + b"NSString"
            + b"\x01\x00\x84\x01+"
            + length_bytes
            + encoded
            + b"trailing"
        )

    def test_none_returns_none(self):
        """Test that None input returns None"""
        # Run function
        result = extract_body_from_attributed(None)

        # Check results
        self.assertIsNone(result)

    def test_empty_bytes_returns_none(self):
        """Test that empty bytes returns None"""
        # Run function
        result = extract_body_from_attributed(b"")

        # Check results
        self.assertIsNone(result)

    def test_garbage_bytes_returns_none(self):
        """Test that random bytes return None without crashing"""
        # Run function
        result = extract_body_from_attributed(b"\x00\x01\x02\x03")

        # Check results
        self.assertIsNone(result)

    def test_valid_short_message(self):
        """Test extracting a short message (length < 0x80)"""
        # Setup
        blob = self._build_blob("Hello")

        # Run function
        result = extract_body_from_attributed(blob)

        # Check results
        self.assertEqual(result, "Hello")

    def test_valid_longer_message(self):
        """Test extracting a message with 2-byte length encoding"""
        # Setup
        content = "A" * 200  # > 0x7F, triggers 0x81 length prefix
        blob = self._build_blob(content)

        # Run function
        result = extract_body_from_attributed(blob)

        # Check results
        self.assertEqual(result, content)

    def test_no_nsstring_marker(self):
        """Test that missing NSString marker returns None"""
        # Setup
        body = b"prefix data with no marker trailing"

        # Run function
        result = extract_body_from_attributed(body)

        # Check results
        self.assertIsNone(result)

    def test_truncated_after_nsstring(self):
        """Test that truncated data after NSString returns None"""
        # Setup - NSString marker but not enough bytes for header
        body = b"NSString\x01\x00"

        # Run function
        result = extract_body_from_attributed(body)

        # Check results
        self.assertIsNone(result)

    def test_random_binary_does_not_crash(self):
        """Test that random binary data doesn't raise exceptions"""
        import os

        # Setup
        random_data = os.urandom(1024)

        # Run function - should not raise
        result = extract_body_from_attributed(random_data)

        # Check results
        self.assertIn(type(result), (str, type(None)))


class TestEscapeAppleScript(unittest.TestCase):
    """Tests for the escape_applescript helper."""

    def test_none_returns_empty(self):
        self.assertEqual(escape_applescript(None), "")

    def test_plain_string_unchanged(self):
        self.assertEqual(escape_applescript("hello world"), "hello world")

    def test_double_quote_escaped(self):
        self.assertEqual(escape_applescript('say "hi"'), 'say \\"hi\\"')

    def test_backslash_escaped_first(self):
        # Backslashes must be escaped before quotes; otherwise the backslash
        # injected by quote-escaping would itself get doubled.
        self.assertEqual(escape_applescript('a\\b"c'), 'a\\\\b\\"c')

    def test_newline_escaped(self):
        self.assertEqual(escape_applescript("a\nb"), "a\\nb")

    def test_carriage_return_escaped(self):
        self.assertEqual(escape_applescript("a\rb"), "a\\nb")

    def test_crlf_escaped(self):
        self.assertEqual(escape_applescript("a\r\nb"), "a\\nb")

    def test_tab_escaped(self):
        self.assertEqual(escape_applescript("a\tb"), "a\\tb")

    def test_unicode_line_separator_escaped(self):
        # U+2028 / U+2029 terminate AppleScript string literals.
        self.assertEqual(escape_applescript("a\u2028b"), "a\\nb")
        self.assertEqual(escape_applescript("a\u2029b"), "a\\nb")

    def test_combined(self):
        self.assertEqual(
            escape_applescript('line1\nline2"end\\'),
            'line1\\nline2\\"end\\\\',
        )


if __name__ == "__main__":
    unittest.main()
