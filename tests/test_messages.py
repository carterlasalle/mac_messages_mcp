# Copyright (c) 2023 Carter Lasalle
"""Tests for the messages module."""

import os
import pathlib
import sqlite3
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

from mac_messages_mcp.messages import (
    _check_imessage_availability,
    _clean_text,
    _connect_sqlite_readonly,
    _find_chat_by_display_name,
    _find_chat_by_identifier,
    _format_phone_for_messages,
    _sanitize_message_body,
    _send_message_to_recipient,
    _verify_send_in_db,
    clean_name,
    escape_applescript,
    extract_body_from_attributed,
    find_contact_by_name,
    find_handles_by_phone,
    get_addressbook_contacts,
    get_chat_mapping,
    get_contact_name,
    get_messages_db_path,
    get_recent_contact_matches,
    get_recent_messages,
    process_contacts,
    run_applescript,
    send_message,
    set_recent_contact_matches,
)

from .test_phone import region_pinned

# Tests for the messages module


@patch("subprocess.Popen")
def test_run_applescript_success(mock_popen):
    """Test running AppleScript successfully."""
    # Setup mock
    process_mock = MagicMock(returncode=0)
    process_mock.communicate.return_value = (b"Success", b"")
    mock_popen.return_value = process_mock

    # Run function
    result = run_applescript('tell application "Messages" to get name')

    # Check results
    assert result == "Success"
    mock_popen.assert_called_with(
        ["osascript", "-e", 'tell application "Messages" to get name'],
        stdout=-1,
        stderr=-1,
    )
    process_mock.communicate.assert_called_once_with(timeout=30)


@patch("subprocess.Popen")
def test_run_applescript_error(mock_popen):
    """Test running AppleScript with error."""
    # Setup mock
    process_mock = MagicMock(returncode=1)
    process_mock.communicate.return_value = (b"", b"Error message")
    mock_popen.return_value = process_mock

    # Run function
    result = run_applescript("invalid script")

    # Check results
    assert result == "Error: Error message"


@patch("subprocess.Popen")
def test_run_applescript_timeout_kills_process(mock_popen):
    process_mock = MagicMock()
    process_mock.communicate.side_effect = [
        subprocess.TimeoutExpired(cmd="osascript", timeout=1),
        (b"", b""),
    ]
    mock_popen.return_value = process_mock

    result = run_applescript("delay 10", timeout=1)

    assert result == "Error: AppleScript timed out after 1 seconds"
    process_mock.kill.assert_called_once_with()


def test_readonly_connection_rejects_writes():
    import pytest

    with tempfile.TemporaryDirectory() as directory:
        db_path = str(pathlib.Path(directory) / "messages.db")
        writable = sqlite3.connect(db_path)
        writable.execute("CREATE TABLE message (id INTEGER)")
        writable.commit()
        writable.close()

        connection = _connect_sqlite_readonly(db_path)
        assert (
            connection.execute("SELECT name FROM sqlite_master").fetchone()[0]
            == "message"
        )
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO message VALUES (1)")
        connection.close()


@patch("os.path.expanduser")
def test_get_messages_db_path(mock_expanduser):
    """Test getting the Messages database path."""
    # Setup mock
    mock_expanduser.return_value = "/Users/testuser"

    # Run function
    result = get_messages_db_path()

    # Check results
    assert result == "/Users/testuser/Library/Messages/chat.db"
    mock_expanduser.assert_called_with("~")


# Tests for AppleScript escaping injection edge cases.


def test_plain_text_unchanged():
    """Test that plain text passes through unchanged."""
    # Run function
    result = escape_applescript("hello world")

    # Check results
    assert result == "hello world"


def test_quotes_escaped():
    """Test that double quotes are escaped."""
    # Run function
    result = escape_applescript('say "hello"')

    # Check results
    assert result == 'say \\"hello\\"'


def test_backslashes_escaped():
    """Test that backslashes are escaped."""
    # Run function
    result = escape_applescript("path\\to\\file")

    # Check results
    assert result == "path\\\\to\\\\file"


def test_escape_order_prevents_injection():
    """Test that backslashes are escaped before quotes to prevent injection."""
    # Setup - a string with backslash-quote that could break AppleScript if
    # quotes are escaped first (producing \\" which unescapes the quote)
    malicious = 'test\\"injection'

    # Run function
    result = escape_applescript(malicious)

    # Check results - backslash escaped first, then quote
    # Input:  test\"injection
    # Step 1: test\\"injection  (backslash escaped)
    # Step 2: test\\\\"injection  (quote escaped)
    assert result == 'test\\\\\\"injection'
    # The result should NOT contain an unescaped quote
    assert '\\"' not in result.replace('\\\\"', "")


def test_empty_string():
    """Test that empty string returns empty string."""
    # Run function
    result = escape_applescript("")

    # Check results
    assert not result


def test_unicode_unchanged():
    """Test that unicode characters pass through unchanged."""
    # Run function
    result = escape_applescript("Hello 世界")

    # Check results
    assert result == "Hello 世界"


# Emoji stripping must not use an overly large regex range.


def test_strips_emoticons_and_dingbats():
    assert _clean_text("Hugo 😀 Example ✂") == "Hugo Example"


def test_preserves_cjk_and_latin_letters():
    assert _clean_text("田中 太郎") == "田中 太郎"
    assert _clean_text("José") == "José"


def test_clean_name_strips_punctuation_after_emoji():
    assert clean_name("Alice 🎉!") == "Alice"


# Tests for MCP-safe message rendering.


def test_control_characters_are_neutralized():
    result = _sanitize_message_body("hello\x00there\x07")
    assert result == "hello\\u0000there\\u0007"
    assert "\x00" not in result
    assert "\x07" not in result


def test_newlines_are_rendered_inline():
    assert _sanitize_message_body("line 1\nline 2") == "line 1\\nline 2"


def test_long_messages_are_truncated():
    result = _sanitize_message_body("abcdef", max_chars=3)
    assert result == "abc... [truncated 3 chars]"


# Tests for _send_message_to_recipient escaping


@patch("mac_messages_mcp.messages.query_messages_db")
@patch("mac_messages_mcp.messages.run_applescript")
def test_does_not_raise_name_error(mock_applescript, mock_query_db):
    """Test that safe_recipient is defined (was NameError after merge)."""
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
        },
    ]

    # Run function — this raised NameError before the fix
    result = _send_message_to_recipient("+15551234567", "hello")

    # Check results
    assert "sent successfully" in result


@patch("mac_messages_mcp.messages.query_messages_db")
@patch("mac_messages_mcp.messages.run_applescript")
def test_recipient_with_quotes_is_escaped(mock_applescript, mock_query_db):
    """Test that quotes in recipient don't break the AppleScript command."""
    # Setup mocks
    mock_applescript.return_value = "Success"
    mock_query_db.return_value = [
        {
            "guid": "abc",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
        },
    ]

    # Run function with a recipient containing quotes
    _send_message_to_recipient('+1234"567', "hello")

    # Check results — the AppleScript command should have escaped quotes
    call_args = mock_applescript.call_args[0][0]
    assert '+1234\\"567' in call_args
    assert '"+1234"567"' not in call_args


# Regression tests for _verify_send_in_db's correlation key.
#
# A plain "latest row after timestamp X, for this handle" query can report
# the wrong outcome when two sends to the same handle land close together:
# whichever call polls last sees the *other* call's row as "the latest
# one". Passing message_text lets each call pick out its own row by body
# match instead of just grabbing whatever is newest.


@patch("mac_messages_mcp.messages.time")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_matches_own_message_among_concurrent_sends(mock_query_db, mock_time):
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

    assert row is not None
    assert row["guid"] == "guid-1"


@patch("mac_messages_mcp.messages.time")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_falls_back_to_latest_row_when_no_body_matches(
    mock_query_db,
    mock_time,
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
        },
    ]

    row = _verify_send_in_db("+15551234567", 0.0, message_text="hello")

    assert row is not None
    assert row["guid"] == "guid-1"


@patch("mac_messages_mcp.messages.time")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_no_message_text_preserves_latest_row_behavior(
    mock_query_db,
    mock_time,
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
        },
    ]

    row = _verify_send_in_db("+15551234567", 0.0)

    assert row is not None
    assert row["guid"] == "guid-newest"


# Tests for recipient formats handed to Messages.app.


def test_phone_formatter_preserves_e164_plus():
    assert _format_phone_for_messages("+19565179045") == "+19565179045"


def test_phone_formatter_does_not_assume_north_america():
    """A ten-digit national number takes its own region's country code, not +1."""
    with region_pinned("FR"):
        assert _format_phone_for_messages("0639980001") == "+33639980001"
        assert _format_phone_for_messages("05 39 98 00 03") == "+33539980003"


def test_phone_formatter_keeps_foreign_e164_intact():
    """An E.164 number is never reinterpreted against the configured region."""
    with region_pinned("US"):
        assert _format_phone_for_messages("+33639980001") == "+33639980001"


def test_phone_formatter_adds_plus_to_country_code_digits():
    with region_pinned("US"):
        assert _format_phone_for_messages("19565179045") == "+19565179045"


def test_phone_formatter_expands_ten_digits_against_configured_region():
    with region_pinned("US"):
        assert _format_phone_for_messages("(956) 517-9045") == "+19565179045"


def test_phone_formatter_rejects_locally_dialable_form():
    """A number dialable only from inside its own area is refused, not expanded.

    Regression: `is_possible_number` is region-relative and accepts a
    seven-digit NANP local under US, so a half-typed number such as
    "555-0142" was expanded to "+15550142" and handed to Messages.app
    instead of being reported back to the caller.
    """
    with region_pinned("US"):
        assert not _format_phone_for_messages("555-0142")
        assert not _format_phone_for_messages("5550142")


def test_phone_formatter_accepts_national_plans_shorter_than_ten_digits():
    """A number is judged by its numbering plan, not by a ten-digit floor.

    Regression: the floor that refused the seven-digit local above was a
    digit count, so it also refused every country whose numbers are
    shorter than the North American ten. Norwegian numbers are eight
    digits and were rejected outright.
    """
    with region_pinned("NO"):
        assert _format_phone_for_messages("22 82 30 00") == "+4722823000"
    with region_pinned("FR"):
        # Nine digits, a legitimate Paris landline in national significant
        # form, refused by the same floor.
        assert _format_phone_for_messages("123456789") == "+33123456789"


def test_phone_formatter_accepts_legitimate_national_and_e164_numbers():
    """Ordinary national and E.164 input is unaffected by the local-form check."""
    with region_pinned("FR"):
        assert _format_phone_for_messages("0639980001") == "+33639980001"
        assert _format_phone_for_messages("+33639980001") == "+33639980001"


@patch("mac_messages_mcp.messages._send_message_to_recipient")
def test_send_message_rejects_locally_dialable_form(mock_send):
    """Report the guard error instead of dispatching a half-typed number."""
    with region_pinned("US"):
        result = send_message("555-0142", "hello")

    assert "is not a usable phone number" in result
    mock_send.assert_not_called()


@patch("mac_messages_mcp.messages._send_message_to_recipient")
def test_send_message_normalizes_bare_digits_before_dispatch(mock_send):
    mock_send.return_value = "sent"

    with region_pinned("US"):
        result = send_message("19565179045", "hello")

    assert result == "sent"
    mock_send.assert_called_once_with(
        "+19565179045",
        "hello",
        group_chat=False,
        attachment_paths=[],
    )


@patch("mac_messages_mcp.messages._send_message_to_recipient")
def test_send_message_rejects_short_phone_numbers(mock_send):
    with region_pinned("US"):
        result = send_message("12345", "hello")

    assert "is not a usable phone number" in result
    mock_send.assert_not_called()


@patch("mac_messages_mcp.messages.get_cached_contacts")
def test_find_contact_returns_messages_ready_phone_number(mock_contacts):
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
            },
        },
        clear=True,
    ):
        matches = find_contact_by_name("Hugo")

    assert matches[0]["phone"] == "+19565179045"


# Tests for temp file race condition fix in _send_message_to_recipient


@patch("mac_messages_mcp.messages.query_messages_db")
@patch("mac_messages_mcp.messages.run_applescript")
def test_temp_file_uses_unique_name(mock_applescript, mock_query_db):
    """Test that temp file gets a unique name (not hardcoded imessage_tmp.txt)."""
    mock_applescript.return_value = ""
    mock_query_db.return_value = [
        {
            "guid": "abc",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
        },
    ]

    # Run function
    _send_message_to_recipient("+15551234567", "test message")

    # Check results - the AppleScript should reference a temp file path
    script = mock_applescript.call_args[0][0]
    # Should NOT use the old hardcoded name
    assert "imessage_tmp.txt" not in script
    # Should reference a unique owner-only mkstemp path
    assert "mac-messages-" in script
    assert (
        tempfile.gettempdir() in script
    ), f"Expected temp directory path in script, got: {script[:200]}"


@patch("mac_messages_mcp.messages.query_messages_db")
@patch("mac_messages_mcp.messages.run_applescript")
def test_temp_file_cleaned_up_on_success(mock_applescript, mock_query_db):
    """Test that temp file is removed after successful send."""
    mock_applescript.return_value = ""
    mock_query_db.return_value = [
        {
            "guid": "abc",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
        },
    ]

    # Count temp files before
    tmpdir = pathlib.Path(tempfile.gettempdir())
    before = set(tmpdir.glob("mac-messages-*.txt"))

    # Run function
    _send_message_to_recipient("+15551234567", "test message")

    after = set(tmpdir.glob("mac-messages-*.txt"))
    leaked = after - before
    assert len(leaked) == 0, f"Temp files leaked: {leaked}"


@patch("mac_messages_mcp.messages.run_applescript")
def test_temp_file_cleaned_up_on_error(mock_applescript):
    """Test that temp file is removed even when AppleScript fails."""
    mock_applescript.return_value = "Error: some failure"

    # Count temp files before
    tmpdir = pathlib.Path(tempfile.gettempdir())
    before = set(tmpdir.glob("mac-messages-*.txt"))

    # Run function (will fall back to _send_message_direct which also uses applescript)
    _send_message_to_recipient("+15551234567", "test message")

    after = set(tmpdir.glob("mac-messages-*.txt"))
    leaked = after - before
    assert len(leaked) == 0, f"Temp files leaked: {leaked}"


@patch("mac_messages_mcp.messages.query_messages_db")
@patch("mac_messages_mcp.messages.run_applescript")
def test_temp_file_is_owner_only(mock_applescript, mock_query_db):
    """Mkstemp must create the message file as 0o600 before AppleScript reads it."""
    import re
    import stat

    seen_mode = {}

    def inspect_script(script):
        match = re.search(r'POSIX file "([^"]+)"', script)
        assert match is not None, script
        path = match.group(1)
        seen_mode["path"] = path
        seen_mode["mode"] = stat.S_IMODE(pathlib.Path(path).stat().st_mode)
        return ""

    mock_applescript.side_effect = inspect_script
    mock_query_db.return_value = [
        {
            "guid": "abc",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
        },
    ]

    _send_message_to_recipient("+15551234567", "secret body")

    assert "mac-messages-" in pathlib.Path(seen_mode["path"]).name
    assert seen_mode["mode"] == 384
    assert not pathlib.Path(seen_mode["path"]).exists()


# Direct DB errors must not fall back to sqlite3 via shell=True.


@patch.dict(os.environ, {}, clear=False)
@patch("mac_messages_mcp.messages.subprocess.run")
@patch("mac_messages_mcp.messages.query_addressbook_db")
def test_db_error_returns_empty_without_shell(mock_query, mock_run):
    os.environ.pop("USE_TEST_DATA", None)
    mock_query.return_value = [{"error": "Cannot access AddressBook database"}]

    result = get_addressbook_contacts()

    assert not result
    mock_run.assert_not_called()


# Tests for get_chat_mapping error handling


@patch("mac_messages_mcp.messages.get_messages_db_path")
def test_returns_mapping(mock_path):
    """Test happy path returns dict of room_name -> display_name."""
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
        assert result == {"room1": "Alice", "room2": "Bob"}
    finally:
        pathlib.Path(db_path).unlink()


@patch("mac_messages_mcp.messages.get_messages_db_path")
def test_inaccessible_db_returns_empty_dict(mock_path):
    """Test that inaccessible database returns empty dict instead of crashing."""
    # Setup
    mock_path.return_value = "/nonexistent/path/chat.db"

    # Run function
    result = get_chat_mapping()

    # Check results
    assert not result


@patch("mac_messages_mcp.messages.get_messages_db_path")
def test_empty_table_returns_empty_dict(mock_path):
    """Test that empty chat table returns empty dict."""
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
        assert not result
    finally:
        pathlib.Path(db_path).unlink()


# Tests for group chat filtering in get_recent_messages.


@patch("mac_messages_mcp.messages.query_messages_db")
def test_find_chat_by_identifier_accepts_short_chat_id(mock_query):
    mock_query.return_value = [
        {
            "ROWID": 7,
            "display_name": "Family",
            "chat_identifier": "iMessage;-;chat123",
            "room_name": "chat123",
        },
    ]

    result = _find_chat_by_identifier("chat123")

    assert result is not None
    assert result["ROWID"] == 7
    params = mock_query.call_args[0][1]
    assert "chat123" in params
    assert "iMessage;-;chat123" in params


@patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
@patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
@patch("mac_messages_mcp.messages.get_contact_name", return_value="Alice")
@patch(
    "mac_messages_mcp.messages._find_chat_by_identifier",
    return_value={"ROWID": 7, "display_name": "Family", "style": 43},
)
@patch("mac_messages_mcp.messages.query_messages_db")
def test_get_recent_messages_filters_by_chat_id(mock_query, *_):
    mock_query.return_value = [
        {
            "ROWID": 100,
            "date": 700_000_000_000_000_000,
            "text": "group hello",
            "attributedBody": None,
            "is_from_me": 0,
            "handle_id": 99,
            "cache_roomnames": None,
        },
    ]

    result = get_recent_messages(hours=24, chat_id="chat123")

    sql, params = mock_query.call_args[0]
    assert "chat_message_join" in sql
    assert 7 in params
    assert "[Family]" in result
    assert "group hello" in result


@patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
@patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
@patch("mac_messages_mcp.messages.get_contact_name", return_value="Poke")
@patch(
    "mac_messages_mcp.messages._find_chat_by_identifier",
    return_value={
        "ROWID": 2264,
        "display_name": "Poke",
        "style": 45,
    },
)
@patch("mac_messages_mcp.messages.query_messages_db")
def test_business_chat_gets_no_name_prefix(mock_query, *_):
    """1:1/business chats (style 45) must not prefix lines with [Name]."""
    mock_query.return_value = [
        {
            "ROWID": 101,
            "date": 700_000_000_000_000_000,
            "text": "biz hello",
            "attributedBody": None,
            "is_from_me": 0,
            "handle_id": 99,
            "cache_roomnames": None,
        },
    ]

    result = get_recent_messages(hours=24, chat_id="urn:biz:6e67a89b")

    assert "[Poke]" not in result
    assert "biz hello" in result


def test_get_recent_messages_rejects_contact_and_chat_id():
    result = get_recent_messages(hours=24, contact="Alice", chat_id="chat123")

    assert "either contact or chat_id" in result


# Tests for Apple epoch timestamp conversion


def test_apple_epoch_constant():
    """Test that 978307200 is the correct offset between Unix and Apple epochs."""
    from datetime import datetime, timezone

    # Setup
    unix_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    apple_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)

    # Run
    delta_seconds = int((apple_epoch - unix_epoch).total_seconds())

    # Check results
    assert delta_seconds == 978307200


def test_nanosecond_timestamp_conversion():
    """Test converting a nanosecond Apple timestamp to a datetime."""
    from datetime import datetime, timezone

    # Setup - a known Apple timestamp in nanoseconds
    # 2025-01-01 00:00:00 UTC = 757382400 seconds after Apple epoch
    apple_epoch_offset = 978307200
    apple_seconds = 757382400
    apple_nanos = apple_seconds * 1_000_000_000

    # Run - convert like the fixed code does
    msg_timestamp_s = apple_nanos / 1_000_000_000
    date_val = datetime.fromtimestamp(
        msg_timestamp_s + apple_epoch_offset,
        tz=timezone.utc,
    )

    # Check results
    expected = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert date_val == expected


def test_second_format_timestamp():
    """Test converting a second-format Apple timestamp."""
    from datetime import datetime, timezone

    # Setup - timestamp already in seconds (len <= 10)
    apple_epoch_offset = 978307200
    apple_seconds = 757382400  # 2025-01-01 00:00:00 UTC

    # Run
    msg_timestamp_s = apple_seconds  # already in seconds, no division needed
    date_val = datetime.fromtimestamp(
        msg_timestamp_s + apple_epoch_offset,
        tz=timezone.utc,
    )

    # Check results
    expected = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert date_val == expected


def _build_blob(text: str) -> bytes:
    """Build a minimal typedstream blob with the given text content."""
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


def test_extract_body_none_returns_none():
    """Test that None input returns None."""
    # Run function
    result = extract_body_from_attributed(None)

    # Check results
    assert result is None


def test_extract_body_empty_bytes_returns_none():
    """Test that empty bytes returns None."""
    # Run function
    result = extract_body_from_attributed(b"")

    # Check results
    assert result is None


def test_extract_body_garbage_bytes_returns_none():
    """Test that random bytes return None without crashing."""
    # Run function
    result = extract_body_from_attributed(b"\x00\x01\x02\x03")

    # Check results
    assert result is None


def test_extract_body_valid_short_message():
    """Test extracting a short message (length < 0x80)."""
    # Setup
    blob = _build_blob("Hello")

    # Run function
    result = extract_body_from_attributed(blob)

    # Check results
    assert result == "Hello"


def test_extract_body_valid_longer_message():
    """Test extracting a message with 2-byte length encoding."""
    # Setup
    content = "A" * 200  # > 0x7F, triggers 0x81 length prefix
    blob = _build_blob(content)

    # Run function
    result = extract_body_from_attributed(blob)

    # Check results
    assert result == content


def test_extract_body_no_nsstring_marker():
    """Test that missing NSString marker returns None."""
    # Setup
    body = b"prefix data with no marker trailing"

    # Run function
    result = extract_body_from_attributed(body)

    # Check results
    assert result is None


def test_extract_body_truncated_after_nsstring():
    """Test that truncated data after NSString returns None."""
    # Setup - NSString marker but not enough bytes for header
    body = b"NSString\x01\x00"

    # Run function
    result = extract_body_from_attributed(body)

    # Check results
    assert result is None


def test_extract_body_random_binary_does_not_crash():
    """Test that random binary data doesn't raise exceptions."""
    # Setup
    random_data = os.urandom(1024)

    # Run function - should not raise
    result = extract_body_from_attributed(random_data)

    # Check results
    assert type(result) in {str, type(None)}


# Tests for the escape_applescript helper.


def test_none_returns_empty():
    assert not escape_applescript(None)


def test_plain_string_unchanged():
    assert escape_applescript("hello world") == "hello world"


def test_double_quote_escaped():
    assert escape_applescript('say "hi"') == 'say \\"hi\\"'


def test_backslash_escaped_first():
    # Backslashes must be escaped before quotes; otherwise the backslash
    # injected by quote-escaping would itself get doubled.
    assert escape_applescript('a\\b"c') == 'a\\\\b\\"c'


def test_newline_escaped():
    assert escape_applescript("a\nb") == "a\\nb"


def test_carriage_return_escaped():
    assert escape_applescript("a\rb") == "a\\nb"


def test_crlf_escaped():
    assert escape_applescript("a\r\nb") == "a\\nb"


def test_tab_escaped():
    assert escape_applescript("a\tb") == "a\\tb"


def test_unicode_line_separator_escaped():
    # U+2028 / U+2029 terminate AppleScript string literals.
    assert escape_applescript("a\u2028b") == "a\\nb"
    assert escape_applescript("a\u2029b") == "a\\nb"


def test_combined():
    assert escape_applescript('line1\nline2"end\\') == 'line1\\nline2\\"end\\\\'


# Tests for _candidate_handles, used by send-delivery verification.


def test_candidate_handles_email():
    from mac_messages_mcp.messages import _candidate_handles

    assert _candidate_handles("a@b.com") == ["a@b.com"]


def test_candidate_handles_international():
    from mac_messages_mcp.messages import _candidate_handles

    handles = _candidate_handles("+447378174086")
    assert "+447378174086" in handles
    assert "447378174086" in handles


def test_candidate_handles_us_number():
    from mac_messages_mcp.messages import _candidate_handles

    with region_pinned("US"):
        handles = _candidate_handles("6058813494")

    assert "6058813494" in handles
    assert "+16058813494" in handles
    assert "16058813494" in handles


# Tests for find_handles_by_phone matching a phone number to stored handle ids.


@patch("mac_messages_mcp.messages.query_messages_db")
def test_e164_input_matches_handle_stored_as_e164(mock_query_db):
    """An E.164 input searches for the E.164 spelling the handle is stored under."""
    mock_query_db.return_value = [{"ROWID": 1}]

    with region_pinned("FR"):
        result = find_handles_by_phone("+33639980001")

    assert result == [1]
    # The regression: the "+" used to be stripped before the lookup, so the
    # query asked for "33639980001" and never matched "+33639980001".
    assert "+33639980001" in mock_query_db.call_args[0][1]


@patch("mac_messages_mcp.messages.query_messages_db")
def test_national_input_finds_same_handle_under_configured_region(
    mock_query_db,
):
    """A national-format input under region FR searches for the FR E.164 spelling."""
    mock_query_db.return_value = [{"ROWID": 2}]

    with region_pinned("FR"):
        result = find_handles_by_phone("06 39 98 00 01")

    assert result == [2]
    searched = mock_query_db.call_args[0][1]
    assert "+33639980001" in searched
    # It must not have been read as a North American number.
    assert "+10639980001" not in searched


@patch("mac_messages_mcp.messages.query_messages_db")
def test_falls_back_to_canonical_scan_when_indexed_lookup_finds_nothing(
    mock_query_db,
):
    """A full-table scan still matches when the indexed lookup misses."""
    mock_query_db.side_effect = [
        [],  # indexed lookup on the predicted variant spellings: no match
        [
            {"ROWID": 3, "id": "0639980001"},  # same number, different spelling
            {"ROWID": 4, "id": "+15555550142"},
        ],
    ]

    with region_pinned("FR"):
        result = find_handles_by_phone("+33639980001")

    assert result == [3]


@patch("mac_messages_mcp.messages.query_messages_db")
def test_no_match_returns_none(mock_query_db):
    """When no stored handle reduces to the same canonical number, None is returned."""
    mock_query_db.side_effect = [
        [],
        [{"ROWID": 4, "id": "+15555550142"}],
    ]

    with region_pinned("FR"):
        result = find_handles_by_phone("+33639980001")

    assert result is None


# Tests that an email handle matches whatever case either side is written in.
#
# handle.id has no declared collation, so SQLite compares it byte for byte.
# Canonicalization lowercases email addresses, so folding only the input
# would trade one miss for another: a handle stored in mixed case would stop
# matching the mixed-case spelling that used to find it.


@patch("mac_messages_mcp.messages.query_messages_db")
def test_mixed_case_email_matches_lowercase_handle(mock_query_db):
    """A mixed-case address is folded before it reaches the query."""
    mock_query_db.return_value = [
        {"ROWID": 1, "service": "iMessage", "text_count": 3, "errors": 0},
    ]

    assert _check_imessage_availability("Hugo.Example@Example.COM")

    query, params = mock_query_db.call_args[0][:2]
    assert "COLLATE NOCASE" in query
    assert params == ("hugo.example@example.com",)


@patch("mac_messages_mcp.messages.query_messages_db")
def test_lowercase_email_still_matches_mixed_case_handle(mock_query_db):
    """The comparison is folded in the query, so the stored case does not matter."""
    mock_query_db.return_value = [
        {"ROWID": 1, "service": "iMessage", "text_count": 3, "errors": 0},
    ]

    assert _check_imessage_availability("hugo.example@example.com")

    # Without COLLATE NOCASE this only works when the stored id happens to
    # be lowercase too.
    assert "COLLATE NOCASE" in mock_query_db.call_args[0][0]


@patch("mac_messages_mcp.messages.find_contact_by_name")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_address_is_not_routed_through_name_matching(
    mock_query_db,
    mock_find_by_name,
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
    assert "No contacts found" not in result


# Tests that an unparseable address book entry stays reachable (regression: H1).
#
# process_contacts used to key the contacts map on canonical_handle(phone)
# under an `if`, so any entry phonenumbers could not parse, an SMS short
# code among them, was silently dropped. It now keys on contact_key, which
# falls back to digits, and get_contact_name looks the handle up through
# lookup_keys so both sides stay symmetric.


def test_process_contacts_keeps_short_code_entry():
    """A contact whose only number is an SMS short code is kept in the map."""
    contacts = [
        {
            "first_name": "Hugo",
            "last_name": "Example",
            "nickname": "",
            "phone": "55501",
            "email": "",
        },
    ]

    with region_pinned("FR"):
        contacts_map = process_contacts(contacts)

    assert contacts_map.get("55501") == "Hugo Example"


@patch("mac_messages_mcp.messages.get_cached_contacts")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_get_contact_name_resolves_short_code_handle(
    mock_query_db,
    mock_contacts,
):
    """Resolve a handle stored as a short code, through lookup_keys."""
    mock_query_db.return_value = [{"id": "55501"}]
    mock_contacts.return_value = {"55501": "Hugo Example"}

    with region_pinned("FR"):
        name = get_contact_name(1)

    assert name == "Hugo Example"


# contact:N selectors resolve across tools from one shared store.
#
# Regression: tool_find_contact printed numbered selectors but never stored
# them, and send_message / get_recent_messages kept disjoint per-function
# caches, so the documented contact:N flow could never resolve.


def setup_function():
    set_recent_contact_matches([])


def teardown_function():
    set_recent_contact_matches([])


def test_store_round_trip():
    matches = [
        {"name": "Ann Example", "phone": "+10000000001", "score": 0.9},
        {"name": "Anya Example", "phone": "+10000000002", "score": 0.8},
    ]
    set_recent_contact_matches(matches)
    assert get_recent_contact_matches() == matches


def test_store_caps_to_displayed_entries():
    matches = [
        {"name": f"Person {i}", "phone": f"+100000000{i:02d}", "score": 0.5}
        for i in range(15)
    ]
    set_recent_contact_matches(matches)
    assert len(get_recent_contact_matches()) == 10


@patch("mac_messages_mcp.messages._send_message_to_recipient")
def test_send_message_resolves_shared_store_selector(mock_send):
    mock_send.return_value = "sent"
    set_recent_contact_matches(
        [
            {"name": "Ann Example", "phone": "+10000000001", "score": 0.9},
            {"name": "Anya Example", "phone": "+10000000002", "score": 0.8},
        ],
    )
    send_message("contact:2", "hello")
    mock_send.assert_called_once_with(
        "+10000000002",
        "hello",
        "Anya Example",
        group_chat=False,
        attachment_paths=[],
    )


# contact= falls back to chat.display_name for named non-AddressBook chats.


@patch("mac_messages_mcp.messages.query_messages_db")
def test_find_chat_by_display_name_exact_match(mock_query):
    mock_query.return_value = [
        {
            "ROWID": 2264,
            "display_name": "Poke",
            "chat_identifier": "urn:biz:6e67a89b",
        },
    ]
    row = _find_chat_by_display_name("poke")
    assert isinstance(row, dict)
    assert row["ROWID"] == 2264
    sql, params = mock_query.call_args[0]
    assert "display_name" in sql
    assert params == ("poke",)


@patch("mac_messages_mcp.messages.query_messages_db")
def test_find_chat_by_display_name_no_match(mock_query):
    mock_query.return_value = []
    assert _find_chat_by_display_name("Nobody") is None


@patch("mac_messages_mcp.messages.query_messages_db")
def test_find_chat_by_display_name_ambiguous(mock_query):
    mock_query.return_value = [
        {"ROWID": 1, "display_name": "Fam", "chat_identifier": "chat1"},
        {"ROWID": 2, "display_name": "Fam", "chat_identifier": "chat2"},
    ]
    rows = _find_chat_by_display_name("Fam")
    assert isinstance(rows, list)
    assert len(rows) == 2


# U+FFFD-only bodies (attachments/buttons) render as [attachment].


def test_replacement_chars_detected():
    from mac_messages_mcp.messages import _is_attachment_placeholder_body

    assert _is_attachment_placeholder_body("�")
    assert _is_attachment_placeholder_body("  ��  ")
    assert not _is_attachment_placeholder_body("hello � world")
    assert not _is_attachment_placeholder_body("")
    assert not _is_attachment_placeholder_body(None)


@patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
@patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
@patch("mac_messages_mcp.messages.get_contact_name", return_value="Poke")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_recent_renders_attachment_placeholder(mock_query, *_):
    mock_query.return_value = [
        {
            "ROWID": 1,
            "date": 700_000_000_000_000_000,
            "text": "\ufffd",
            "attributedBody": None,
            "is_from_me": 0,
            "handle_id": 99,
            "cache_roomnames": None,
        },
    ]
    result = get_recent_messages(hours=24)
    assert "[attachment]" in result
    assert "�" not in result
