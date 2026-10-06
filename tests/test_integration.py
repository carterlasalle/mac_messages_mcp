# Copyright (c) 2023 Carter Lasalle
"""Integration tests for Mac Messages MCP server.

Tests all MCP tools to ensure they don't crash and handle edge cases properly.
"""

import os

from mac_messages_mcp.messages import (
    _check_imessage_availability,
    _send_message_sms,
    check_addressbook_access,
    check_messages_db_access,
    extract_body_from_attributed,
    fuzzy_search_messages,
    get_recent_messages,
)


def test_import_fixes():
    """Test that the critical import fixes work."""
    from thefuzz import fuzz

    assert fuzz.ratio("abc", "abc") == 100


def test_input_validation():
    """Test input validation prevents crashes."""
    # Test negative hours
    result = get_recent_messages(hours=-1)
    assert "Error: Hours cannot be negative" in result

    # Test overflow hours
    result = get_recent_messages(hours=999999999)
    assert "Error: Hours value too large" in result

    # Test empty search term
    result = fuzzy_search_messages("")
    assert "Error: Search term cannot be empty" in result

    # Test invalid threshold
    result = fuzzy_search_messages("test", threshold=-0.1)
    assert "Error: Threshold must be between 0.0 and 1.0" in result


def test_contact_selection_validation():
    """Test contact selection validation."""
    # Test invalid contact formats
    test_cases = [
        ("contact:", "Error: Invalid contact selection format"),
        ("contact:abc", "Error: Contact selection must be a number"),
        ("contact:-1", "Error: Contact selection must be a positive number"),
        ("contact:0", "Error: Contact selection must be a positive number"),
    ]

    for contact, expected_error in test_cases:
        result = get_recent_messages(contact=contact)
        assert (
            expected_error in result
        ), f"Expected '{expected_error}' in result for '{contact}'"


def test_no_crashes():
    """Test that basic functionality doesn't crash."""
    # Test basic message retrieval
    result = get_recent_messages(hours=1)
    assert isinstance(result, str)
    assert "NameError" not in result
    assert "name 'fuzz' is not defined" not in result

    # Test fuzzy search
    result = fuzzy_search_messages("test", hours=1)
    assert isinstance(result, str)
    assert "NameError" not in result
    assert "name 'fuzz' is not defined" not in result

    # Test database access checks
    result = check_messages_db_access()
    assert isinstance(result, str)

    result = check_addressbook_access()
    assert isinstance(result, str)


def test_time_ranges():
    """Test various time ranges that previously failed."""
    time_ranges = [1, 24, 168, 720, 2160, 4320, 8760]  # 1h to 1 year

    for hours in time_ranges:
        result = get_recent_messages(hours=hours)
        assert isinstance(result, str)
        assert "Python int too large" not in result
        assert "NameError" not in result


def test_sms_fallback_functionality():
    """Test SMS/RCS fallback functions don't crash with import errors."""
    # Test iMessage availability check
    result = _check_imessage_availability("+15551234567")
    assert isinstance(
        result,
        bool,
    ), "iMessage availability check should return boolean"

    # Test SMS sending function
    result = _send_message_sms("+15551234567", "test message")
    assert isinstance(result, str), "SMS send should return string result"


def test_applescript_escape_order():
    """Test that AppleScript escaping uses correct order to prevent injection."""
    from mac_messages_mcp.messages import escape_applescript

    # Wrong order (quotes first, then backslashes) turns \" into \\"
    # which leaves the quote unescaped. Correct order escapes the
    # backslash first, then the quote, so both are safely neutralized.
    malicious = 'test\\"break'
    result = escape_applescript(malicious)
    expected = 'test\\\\\\"break'
    assert result == expected, f"Expected {expected!r}, got {result!r}"


def test_attributed_body_extraction():
    """Test attributedBody binary decoding handles edge cases."""
    # None input
    assert extract_body_from_attributed(None) is None

    # Empty bytes
    assert extract_body_from_attributed(b"") is None

    # Garbage bytes
    assert extract_body_from_attributed(b"\x00\x01\x02\x03") is None

    # Valid structure: NSString + 5-byte header + length byte + text
    content = "Hello from iMessage"
    encoded = content.encode("utf-8")
    body = (
        b"prefix"
        + b"NSString"
        + b"\x01\x00\x84\x01+"  # 5-byte header
        + bytes([len(encoded)])  # length byte (< 0x80)
        + encoded
        + b"trailing"
    )
    result = extract_body_from_attributed(body)
    assert result == content, f"Expected {content!r}, got {result!r}"

    # Random binary data should not crash
    result = extract_body_from_attributed(os.urandom(1024))
    assert result is None or isinstance(result, str)


def run_all_tests():
    """Run all tests and report results."""
    import pytest

    return pytest.main([__file__]) == 0


if __name__ == "__main__":
    raise SystemExit(run_all_tests())
