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
    _check_imessage_availability,
    _connect_sqlite_readonly,
    _find_chat_by_identifier,
    _format_phone_for_messages,
    _sanitize_message_body,
    _send_message_to_recipient,
    _verify_send_in_db,
    escape_applescript,
    extract_body_from_attributed,
    find_contact_by_name,
    find_handles_by_phone,
    get_chat_mapping,
    get_contact_name,
    get_messages_db_path,
    get_recent_messages,
    process_contacts,
    query_messages_db,
    run_applescript,
    send_message,
)
from tests.test_phone import region_pinned


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

    def test_control_characters_are_neutralized(self):
        result = _sanitize_message_body("hello\x00there\x07")
        self.assertEqual(result, "hello\\u0000there\\u0007")
        self.assertNotIn("\x00", result)
        self.assertNotIn("\x07", result)

    def test_newlines_are_rendered_inline(self):
        self.assertEqual(_sanitize_message_body("line 1\nline 2"), "line 1\\nline 2")

    def test_long_messages_are_truncated(self):
        result = _sanitize_message_body("abcdef", max_chars=3)
        self.assertEqual(result, "abc... [truncated 3 chars]")


class TestSendMessageToRecipient(unittest.TestCase):
    """Tests for _send_message_to_recipient escaping"""

    @patch("mac_messages_mcp.messages.query_messages_db")
    @patch("mac_messages_mcp.messages.run_applescript")
    def test_does_not_raise_name_error(self, mock_applescript, mock_query_db):
        """Test that safe_recipient is defined (was NameError after merge)"""
        from mac_messages_mcp.messages import _send_message_to_recipient

        # Setup mocks: AppleScript accepts the send, and chat.db shows it
        # went through so the result reports success rather than the
        # NameError this used to raise.
        mock_applescript.return_value = "Success"
        mock_query_db.return_value = [
            {
                "guid": "abc",
                "send_error": 0,
                "is_sent": 1,
                "is_delivered": 0,
                "service": "iMessage",
            }
        ]

        # Run function — this raised NameError before the fix
        result = _send_message_to_recipient("+15551234567", "hello")

        # Check results
        self.assertIn("sent successfully", result)

    @patch("mac_messages_mcp.messages.query_messages_db")
    @patch("mac_messages_mcp.messages.run_applescript")
    def test_recipient_with_quotes_is_escaped(self, mock_applescript, mock_query_db):
        """Test that quotes in recipient don't break the AppleScript command"""
        from mac_messages_mcp.messages import _send_message_to_recipient

        # Setup mocks
        mock_applescript.return_value = "Success"
        mock_query_db.return_value = [
            {
                "guid": "abc",
                "send_error": 0,
                "is_sent": 1,
                "is_delivered": 0,
                "service": "iMessage",
            }
        ]

        # Run function with a recipient containing quotes
        _send_message_to_recipient('+1234"567', "hello")

        # Check results — the AppleScript command should have escaped quotes
        call_args = mock_applescript.call_args[0][0]
        self.assertIn('+1234\\"567', call_args)
        self.assertNotIn('"+1234"567"', call_args)


class TestVerifySendInDbCorrelation(unittest.TestCase):
    """
    Regression tests for _verify_send_in_db's correlation key.

    A plain "latest row after timestamp X, for this handle" query can report
    the wrong outcome when two sends to the same handle land close together:
    whichever call polls last sees the *other* call's row as "the latest
    one". Passing message_text lets each call pick out its own row by body
    match instead of just grabbing whatever is newest.
    """

    @patch("mac_messages_mcp.messages.time")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_matches_own_message_among_concurrent_sends(self, mock_query_db, mock_time):
        # Two sends to the same handle landed in chat.db between when this
        # call started polling and now; only the second one is this call's.
        mock_time.time.side_effect = [0.0, 0.0]
        mock_query_db.return_value = [
            {
                "guid": "guid-2",
                "send_error": 0,
                "is_sent": 1,
                "is_delivered": 0,
                "service": "iMessage",
                "text": "second message",
                "attributedBody": None,
            },
            {
                "guid": "guid-1",
                "send_error": 0,
                "is_sent": 1,
                "is_delivered": 0,
                "service": "iMessage",
                "text": "first message",
                "attributedBody": None,
            },
        ]

        row = _verify_send_in_db("+15551234567", 0.0, message_text="first message")

        self.assertEqual(row["guid"], "guid-1")

    @patch("mac_messages_mcp.messages.time")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_falls_back_to_latest_row_when_no_body_matches(
        self, mock_query_db, mock_time
    ):
        # e.g. an attachment-only send, or Messages re-encoding the text --
        # don't report a false negative just because the body didn't match.
        mock_time.time.side_effect = [0.0, 0.0]
        mock_query_db.return_value = [
            {
                "guid": "guid-1",
                "send_error": 0,
                "is_sent": 1,
                "is_delivered": 0,
                "service": "iMessage",
                "text": None,
                "attributedBody": None,
            }
        ]

        row = _verify_send_in_db("+15551234567", 0.0, message_text="hello")

        self.assertEqual(row["guid"], "guid-1")

    @patch("mac_messages_mcp.messages.time")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_no_message_text_preserves_latest_row_behavior(
        self, mock_query_db, mock_time
    ):
        mock_time.time.side_effect = [0.0, 0.0]
        mock_query_db.return_value = [
            {
                "guid": "guid-newest",
                "send_error": 0,
                "is_sent": 1,
                "is_delivered": 0,
                "service": "iMessage",
                "text": "whatever",
                "attributedBody": None,
            }
        ]

        row = _verify_send_in_db("+15551234567", 0.0)

        self.assertEqual(row["guid"], "guid-newest")


class TestRecipientNormalization(unittest.TestCase):
    """Tests for recipient formats handed to Messages.app."""

    def test_phone_formatter_preserves_e164_plus(self):
        self.assertEqual(_format_phone_for_messages("+19565179045"), "+19565179045")

    def test_phone_formatter_does_not_assume_north_america(self):
        """A ten-digit national number takes its own region's country code, not +1."""
        with region_pinned("FR"):
            self.assertEqual(_format_phone_for_messages("0639980001"), "+33639980001")
            self.assertEqual(
                _format_phone_for_messages("05 39 98 00 03"), "+33539980003"
            )

    def test_phone_formatter_keeps_foreign_e164_intact(self):
        """An E.164 number is never reinterpreted against the configured region."""
        with region_pinned("US"):
            self.assertEqual(_format_phone_for_messages("+33639980001"), "+33639980001")

    def test_phone_formatter_adds_plus_to_country_code_digits(self):
        with region_pinned("US"):
            self.assertEqual(_format_phone_for_messages("19565179045"), "+19565179045")

    def test_phone_formatter_expands_ten_digits_against_configured_region(self):
        with region_pinned("US"):
            self.assertEqual(
                _format_phone_for_messages("(956) 517-9045"), "+19565179045"
            )

    def test_phone_formatter_rejects_locally_dialable_form(self):
        """A number dialable only from inside its own area is refused, not expanded.

        Regression: `is_possible_number` is region-relative and accepts a
        seven-digit NANP local under US, so a half-typed number such as
        "555-0142" was expanded to "+15550142" and handed to Messages.app
        instead of being reported back to the caller.
        """
        with region_pinned("US"):
            self.assertEqual(_format_phone_for_messages("555-0142"), "")
            self.assertEqual(_format_phone_for_messages("5550142"), "")

    def test_phone_formatter_accepts_national_plans_shorter_than_ten_digits(self):
        """A number is judged by its numbering plan, not by a ten-digit floor.

        Regression: the floor that refused the seven-digit local above was a
        digit count, so it also refused every country whose numbers are
        shorter than the North American ten. Norwegian numbers are eight
        digits and were rejected outright.
        """
        with region_pinned("NO"):
            self.assertEqual(_format_phone_for_messages("22 82 30 00"), "+4722823000")
        with region_pinned("FR"):
            # Nine digits, a legitimate Paris landline in national significant
            # form, refused by the same floor.
            self.assertEqual(_format_phone_for_messages("123456789"), "+33123456789")

    def test_phone_formatter_accepts_legitimate_national_and_e164_numbers(self):
        """Ordinary national and E.164 input is unaffected by the local-form check."""
        with region_pinned("FR"):
            self.assertEqual(_format_phone_for_messages("0639980001"), "+33639980001")
            self.assertEqual(_format_phone_for_messages("+33639980001"), "+33639980001")

    @patch("mac_messages_mcp.messages._send_message_to_recipient")
    def test_send_message_rejects_locally_dialable_form(self, mock_send):
        """send_message reports the guard error instead of dispatching a half-typed number."""
        with region_pinned("US"):
            result = send_message("555-0142", "hello")

        self.assertIn("is not a usable phone number", result)
        mock_send.assert_not_called()

    @patch("mac_messages_mcp.messages._send_message_to_recipient")
    def test_send_message_normalizes_bare_digits_before_dispatch(self, mock_send):
        mock_send.return_value = "sent"

        with region_pinned("US"):
            result = send_message("19565179045", "hello")

        self.assertEqual(result, "sent")
        mock_send.assert_called_once_with("+19565179045", "hello", group_chat=False)

    @patch("mac_messages_mcp.messages._send_message_to_recipient")
    def test_send_message_rejects_short_phone_numbers(self, mock_send):
        with region_pinned("US"):
            result = send_message("12345", "hello")

        self.assertIn("is not a usable phone number", result)
        mock_send.assert_not_called()

    @patch("mac_messages_mcp.messages.get_cached_contacts")
    def test_find_contact_returns_messages_ready_phone_number(self, mock_contacts):
        # The contacts map is keyed on canonical E.164 form.
        mock_contacts.return_value = {"+19565179045": "Hugo Example"}
        with patch.dict(
            "mac_messages_mcp.messages._PHONE_TO_DETAILS_MAP",
            {
                "+19565179045": {
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

    @patch("mac_messages_mcp.messages.query_messages_db")
    @patch("mac_messages_mcp.messages.run_applescript")
    def test_temp_file_uses_unique_name(self, mock_applescript, mock_query_db):
        """Test that temp file gets a unique name (not hardcoded imessage_tmp.txt)"""
        import os

        mock_applescript.return_value = ""
        mock_query_db.return_value = [
            {
                "guid": "abc",
                "send_error": 0,
                "is_sent": 1,
                "is_delivered": 0,
                "service": "iMessage",
            }
        ]

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

    @patch("mac_messages_mcp.messages.query_messages_db")
    @patch("mac_messages_mcp.messages.run_applescript")
    def test_temp_file_cleaned_up_on_success(self, mock_applescript, mock_query_db):
        """Test that temp file is removed after successful send"""
        import glob
        import os

        mock_applescript.return_value = ""
        mock_query_db.return_value = [
            {
                "guid": "abc",
                "send_error": 0,
                "is_sent": 1,
                "is_delivered": 0,
                "service": "iMessage",
            }
        ]

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


class TestCandidateHandles(unittest.TestCase):
    """Tests for _candidate_handles, used by send-delivery verification."""

    def test_candidate_handles_email(self):
        from mac_messages_mcp.messages import _candidate_handles

        self.assertEqual(_candidate_handles("a@b.com"), ["a@b.com"])

    def test_candidate_handles_international(self):
        from mac_messages_mcp.messages import _candidate_handles

        handles = _candidate_handles("+447378174086")
        self.assertIn("+447378174086", handles)
        self.assertIn("447378174086", handles)

    def test_candidate_handles_us_number(self):
        from mac_messages_mcp.messages import _candidate_handles

        with region_pinned("US"):
            handles = _candidate_handles("6058813494")

        self.assertIn("6058813494", handles)
        self.assertIn("+16058813494", handles)
        self.assertIn("16058813494", handles)


class TestFindHandlesByPhone(unittest.TestCase):
    """Tests for find_handles_by_phone matching a phone number to stored handle ids."""

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_e164_input_matches_handle_stored_as_e164(self, mock_query_db):
        """An E.164 input searches for the E.164 spelling the handle is stored under."""
        mock_query_db.return_value = [{"ROWID": 1}]

        with region_pinned("FR"):
            result = find_handles_by_phone("+33639980001")

        self.assertEqual(result, [1])
        # The regression: the "+" used to be stripped before the lookup, so the
        # query asked for "33639980001" and never matched "+33639980001".
        self.assertIn("+33639980001", mock_query_db.call_args[0][1])

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_national_input_finds_same_handle_under_configured_region(
        self, mock_query_db
    ):
        """A national-format input under region FR searches for the FR E.164 spelling."""
        mock_query_db.return_value = [{"ROWID": 2}]

        with region_pinned("FR"):
            result = find_handles_by_phone("06 39 98 00 01")

        self.assertEqual(result, [2])
        searched = mock_query_db.call_args[0][1]
        self.assertIn("+33639980001", searched)
        # It must not have been read as a North American number.
        self.assertNotIn("+10639980001", searched)

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_falls_back_to_canonical_scan_when_indexed_lookup_finds_nothing(
        self, mock_query_db
    ):
        """When the WHERE id IN (...) lookup misses, a full-table canonical scan still matches."""
        mock_query_db.side_effect = [
            [],  # indexed lookup on the predicted variant spellings: no match
            [
                {"ROWID": 3, "id": "0639980001"},  # same number, different spelling
                {"ROWID": 4, "id": "+15555550142"},
            ],
        ]

        with region_pinned("FR"):
            result = find_handles_by_phone("+33639980001")

        self.assertEqual(result, [3])

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_no_match_returns_none(self, mock_query_db):
        """When no stored handle reduces to the same canonical number, None is returned."""
        mock_query_db.side_effect = [
            [],
            [{"ROWID": 4, "id": "+15555550142"}],
        ]

        with region_pinned("FR"):
            result = find_handles_by_phone("+33639980001")

        self.assertIsNone(result)


class TestEmailHandleCaseFolding(unittest.TestCase):
    """Tests that an email handle matches whatever case either side is written in.

    handle.id has no declared collation, so SQLite compares it byte for byte.
    Canonicalization lowercases email addresses, so folding only the input
    would trade one miss for another: a handle stored in mixed case would stop
    matching the mixed-case spelling that used to find it.
    """

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_mixed_case_email_matches_lowercase_handle(self, mock_query_db):
        """A mixed-case address is folded before it reaches the query."""
        mock_query_db.return_value = [
            {"ROWID": 1, "service": "iMessage", "text_count": 3, "errors": 0}
        ]

        self.assertTrue(_check_imessage_availability("Hugo.Example@Example.COM"))

        query, params = mock_query_db.call_args[0][:2]
        self.assertIn("COLLATE NOCASE", query)
        self.assertEqual(params, ("hugo.example@example.com",))

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_lowercase_email_still_matches_mixed_case_handle(self, mock_query_db):
        """The comparison is folded in the query, so the stored case does not matter."""
        mock_query_db.return_value = [
            {"ROWID": 1, "service": "iMessage", "text_count": 3, "errors": 0}
        ]

        self.assertTrue(_check_imessage_availability("hugo.example@example.com"))

        # Without COLLATE NOCASE this only works when the stored id happens to
        # be lowercase too.
        self.assertIn("COLLATE NOCASE", mock_query_db.call_args[0][0])

    @patch("mac_messages_mcp.messages.find_contact_by_name")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_address_is_not_routed_through_name_matching(
        self, mock_query_db, mock_find_by_name
    ):
        """An address reaches the handle lookup instead of fuzzy name matching.

        An address contains letters, so the guard that separates names from
        numbers sent it to find_contact_by_name, which answered "No contacts
        found" for anyone whose address is not in the address book and
        returned before the handle query could run.
        """
        mock_query_db.return_value = []
        mock_find_by_name.return_value = []

        result = get_recent_messages(hours=1, contact="hugo.example@example.com")

        mock_find_by_name.assert_not_called()
        self.assertNotIn("No contacts found", result)


class TestAddressBookShortCodeRegression(unittest.TestCase):
    """Tests that an unparseable address book entry stays reachable (regression: H1).

    process_contacts used to key the contacts map on canonical_handle(phone)
    under an `if`, so any entry phonenumbers could not parse, an SMS short
    code among them, was silently dropped. It now keys on contact_key, which
    falls back to digits, and get_contact_name looks the handle up through
    lookup_keys so both sides stay symmetric.
    """

    def test_process_contacts_keeps_short_code_entry(self):
        """A contact whose only number is an SMS short code is kept in the map."""
        contacts = [
            {
                "first_name": "Hugo",
                "last_name": "Example",
                "nickname": "",
                "phone": "55501",
                "email": "",
            }
        ]

        with region_pinned("FR"):
            contacts_map = process_contacts(contacts)

        self.assertEqual(contacts_map.get("55501"), "Hugo Example")

    @patch("mac_messages_mcp.messages.get_cached_contacts")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_get_contact_name_resolves_short_code_handle(
        self, mock_query_db, mock_contacts
    ):
        """get_contact_name resolves a handle stored as a short code, through lookup_keys."""
        mock_query_db.return_value = [{"id": "55501"}]
        mock_contacts.return_value = {"55501": "Hugo Example"}

        with region_pinned("FR"):
            name = get_contact_name(1)

        self.assertEqual(name, "Hugo Example")


if __name__ == "__main__":
    unittest.main()
