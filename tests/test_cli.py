# Copyright (c) 2023 Carter Lasalle
"""Tests for the mac-messages-cli command-line interface.

Style follows the rest of the suite: pytest-style functions with mocking. The
CLI binds its core functions at import time, so these tests patch
``mac_messages_mcp.cli.<name>`` with plain stub functions (a stub has no
``__wrapped__`` and is therefore not unwrapped further).
"""

import io
import sys
from unittest.mock import patch

import pytest

from mac_messages_mcp import cli
from mac_messages_mcp.untrusted import UNTRUSTED_OPEN, bound_untrusted_output


class _FakeTTY(io.StringIO):
    """A StringIO that claims to be a terminal, so ``input()`` can be driven."""

    def isatty(self) -> bool:
        return True


def test_unwrap_returns_undecorated_function():
    def core(hours):
        return f"hours={hours}"

    decorated = bound_untrusted_output(core)
    assert decorated is not core
    assert cli._unwrap(decorated) is core
    assert cli._unwrap(core) is core


def test_recent_prints_unfenced_output(capsys):
    """A decorated core function is printed without the MCP fence or escaping."""

    def core(*, hours, contact, chat_id):
        return "line one\nline two"

    with patch(
        "mac_messages_mcp.cli.get_recent_messages", new=bound_untrusted_output(core)
    ):
        assert cli.main(["recent", "-n", "3"]) == 0

    out = capsys.readouterr().out
    assert out == "line one\nline two\n"
    assert UNTRUSTED_OPEN not in out


def test_recent_reports_error_with_failing_exit_code(capsys):
    def core(*, hours, contact, chat_id):
        return "Error: Hours cannot be negative."

    with patch("mac_messages_mcp.cli.get_recent_messages", new=core):
        assert cli.main(["recent", "-n", "-1"]) == 1

    assert "Error: Hours cannot be negative." in capsys.readouterr().out


def test_send_refuses_without_confirmation_when_stdin_is_not_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with patch("mac_messages_mcp.cli.send_message") as send:
        assert cli.main(["send", "+15551234567", "hello"]) == 2

    send.assert_not_called()
    assert "Refusing to send" in capsys.readouterr().err


def test_send_cancelled_at_prompt_does_not_send(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _FakeTTY("n\n"))
    with patch("mac_messages_mcp.cli.send_message") as send:
        assert cli.main(["send", "+15551234567", "hello"]) == 1

    send.assert_not_called()
    assert "Cancelled" in capsys.readouterr().out


def test_send_yes_sends_and_routes_group_flag(capsys):
    with patch(
        "mac_messages_mcp.cli.send_message",
        return_value="Message sent successfully",
    ) as send:
        assert cli.main(["send", "chat123", "hello", "--group", "--yes"]) == 0

    assert send.call_args.kwargs["group_chat"] is True
    assert send.call_args.kwargs["recipient"] == "chat123"
    assert send.call_args.kwargs["message"] == "hello"
    assert "Message sent successfully" in capsys.readouterr().out


def test_send_failure_returns_nonzero(capsys):
    with patch(
        "mac_messages_mcp.cli.send_message",
        return_value="Error sending message: not signed in",
    ):
        assert cli.main(["send", "+15551234567", "hello", "--yes"]) == 1

    assert "Error sending message" in capsys.readouterr().out


def test_contact_lists_numbered_matches(capsys):
    matches = [
        {"name": "Example Contact", "phone": "+15550000001", "score": 0.91},
        {"name": "Example Other", "phone": "+15550000002", "score": 0.72},
    ]
    with patch("mac_messages_mcp.cli.find_contact_by_name", return_value=matches):
        assert cli.main(["contact", "Example"]) == 0

    out = capsys.readouterr().out
    assert "Found 2 contacts matching 'Example':" in out
    assert "1. Example Contact (+15550000001) - confidence 0.91" in out
    assert "2. Example Other (+15550000002) - confidence 0.72" in out


def test_contact_without_matches_is_a_lookup_failure(capsys):
    with patch("mac_messages_mcp.cli.find_contact_by_name", return_value=[]):
        assert cli.main(["contact", "Nobody"]) == 1

    assert "No contacts found matching 'Nobody'." in capsys.readouterr().out


def test_chats_lists_names_and_ids(capsys):
    rows = [
        {"display_name": "Example Group", "chat_identifier": "chat123"},
        {"display_name": "", "chat_identifier": "chat-empty"},
    ]
    with patch("mac_messages_mcp.cli.query_messages_db", return_value=rows):
        assert cli.main(["chats"]) == 0

    out = capsys.readouterr().out
    assert "1. Example Group (ID: chat123)" in out
    assert "chat-empty" not in out


def test_chats_database_error_returns_nonzero(capsys):
    rows = [{"error": "unable to open database file"}]
    with patch("mac_messages_mcp.cli.query_messages_db", return_value=rows):
        assert cli.main(["chats"]) == 1

    assert (
        "Error accessing chats: unable to open database file" in capsys.readouterr().out
    )


def test_attachment_saves_file_to_requested_path(tmp_path, capsys):
    source = tmp_path / "invitation.jpg"
    source.write_bytes(b"jpeg-bytes")
    destination = tmp_path / "copy.jpg"
    summary = f"Attachment 42: image/jpeg | invitation.jpg | 0.1 KB | path: {source}"

    with patch(
        "mac_messages_mcp.cli._describe_attachment",
        return_value=(summary, str(source)),
    ):
        assert cli.main(["attachment", "42", "--save", str(destination)]) == 0

    assert destination.read_bytes() == b"jpeg-bytes"
    out = capsys.readouterr().out
    assert summary in out
    assert f"Saved to {destination}" in out


def test_attachment_missing_file_returns_nonzero(capsys):
    summary = "Attachment 42: missing on disk at /nowhere/invitation.jpg"
    with patch(
        "mac_messages_mcp.cli._describe_attachment",
        return_value=(summary, None),
    ):
        assert cli.main(["attachment", "42"]) == 1

    assert summary in capsys.readouterr().out


def test_check_reports_both_databases_and_exit_code(capsys):
    with (
        patch(
            "mac_messages_mcp.cli.check_messages_db_access",
            return_value="Successfully connected to database",
        ),
        patch(
            "mac_messages_mcp.cli.check_addressbook_access",
            return_value="ERROR: AddressBook Sources directory not found",
        ),
    ):
        assert cli.main(["check"]) == 1

    out = capsys.readouterr().out
    assert "== Messages database ==" in out
    assert "== AddressBook ==" in out
    assert "Successfully connected to database" in out


def test_check_recipient_reports_sms_fallback(capsys):
    with (
        patch("mac_messages_mcp.cli.check_messages_db_access", return_value="ok"),
        patch("mac_messages_mcp.cli.check_addressbook_access", return_value="ok"),
        patch("mac_messages_mcp.cli._check_imessage_availability", return_value=False),
    ):
        assert cli.main(["check", "--recipient", "+15551234567"]) == 0

    assert (
        "+15551234567: no iMessage; messages fall back to SMS/RCS"
        in capsys.readouterr().out
    )


def test_check_recipient_email_reports_no_sms(capsys):
    with (
        patch("mac_messages_mcp.cli.check_messages_db_access", return_value="ok"),
        patch("mac_messages_mcp.cli.check_addressbook_access", return_value="ok"),
        patch("mac_messages_mcp.cli._check_imessage_availability", return_value=False),
    ):
        assert cli.main(["check", "--recipient", "someone@example.com"]) == 0

    assert "someone@example.com: no iMessage" in capsys.readouterr().out


def test_version_flag_prints_package_version(capsys):
    from mac_messages_mcp import __version__

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])

    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_missing_command_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])

    assert excinfo.value.code == 2
