# Copyright (c) 2023 Carter Lasalle
"""Coverage for the write-side and server-surface features.

Attachments, Contact creation, in-memory scheduling, and the elicitation-backed
send confirmation. AppleScript is always mocked; nothing is sent.
"""

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import patch

from mac_messages_mcp.messages import create_contact, send_message
from mac_messages_mcp.server import (
    draft_reply,
    scheduler,
    summarize_recent_messages,
    tool_cancel_scheduled_message,
    tool_create_contact,
    tool_list_conversations,
    tool_list_scheduled_messages,
    tool_schedule_message,
    tool_search_attachment_contents,
    tool_send_message,
    tool_wait_for_new_messages,
    triage_unread_messages,
)

# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


@patch(
    "mac_messages_mcp.messages._send_via_temp_file",
    return_value="Message sent successfully via iMessage to Bob",
)
@patch("mac_messages_mcp.messages.run_applescript")
def test_send_with_attachment_reports_the_file(mock_applescript, _temp, tmp_path):
    mock_applescript.return_value = ""
    doc = tmp_path / "report.pdf"
    doc.write_bytes(b"%PDF-1.4")

    result = send_message("+15551234567", "here you go", attachment_paths=[str(doc)])

    assert "report.pdf sent" in result
    script = mock_applescript.call_args[0][0]
    assert "POSIX file" in script
    assert str(doc.resolve()) in script


@patch("mac_messages_mcp.messages.run_applescript", return_value="")
def test_attachment_only_send_needs_no_text(mock_applescript, tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("hi", encoding="utf-8")

    result = send_message("+15551234567", "", attachment_paths=[str(doc)])

    assert "Sent 1 attachment(s) via iMessage" in result
    assert "notes.txt sent" in result


@patch("mac_messages_mcp.messages.run_applescript")
def test_failed_attachment_is_reported_without_blocking_the_text(
    mock_applescript,
    tmp_path,
):
    mock_applescript.side_effect = ["Error: no iMessage account", ""]
    doc = tmp_path / "photo.jpg"
    doc.write_bytes(b"\xff\xd8")

    with patch(
        "mac_messages_mcp.messages._send_via_temp_file",
        return_value="Message sent successfully via iMessage to Bob",
    ):
        result = send_message("+15551234567", "caption", attachment_paths=[str(doc)])

    assert "photo.jpg failed (no iMessage account)" in result
    assert "Message sent successfully" in result


def test_group_chat_attachments_are_refused(tmp_path):
    doc = tmp_path / "a.txt"
    doc.write_text("x", encoding="utf-8")

    result = send_message("chat1", "hi", group_chat=True, attachment_paths=[str(doc)])

    assert "attachments can only be sent to an individual recipient" in result


def test_missing_attachment_path_is_rejected_before_sending(tmp_path):
    with patch("mac_messages_mcp.messages._send_message_to_recipient") as dispatch:
        result = send_message(
            "+15551234567",
            "hi",
            attachment_paths=[str(tmp_path / "nope.txt")],
        )

    assert "attachment not found" in result
    dispatch.assert_not_called()


def test_directory_attachment_is_rejected(tmp_path):
    result = send_message("+15551234567", "hi", attachment_paths=[str(tmp_path)])

    assert "not a regular file" in result


def test_empty_message_without_attachments_is_rejected():
    result = send_message("+15551234567", "   ")

    assert "provide message text or at least one attachment" in result


# ---------------------------------------------------------------------------
# Contact creation
# ---------------------------------------------------------------------------


@patch("mac_messages_mcp.messages.run_applescript", return_value="success")
def test_create_contact_splits_the_name_and_keeps_e164(mock_applescript):
    result = create_contact("Ada Lovelace", "+15551234567")

    assert "Created contact Ada Lovelace" in result
    assert "+15551234567" in result
    script = mock_applescript.call_args[0][0]
    assert 'first name:"Ada"' in script
    assert 'last name:"Lovelace"' in script
    assert 'value:"+15551234567"' in script
    assert 'label:"mobile"' in script


@patch("mac_messages_mcp.messages.run_applescript", return_value="success")
def test_create_contact_supports_single_names_and_labels(mock_applescript):
    create_contact("Prince", "+15551234567", label="home")

    script = mock_applescript.call_args[0][0]
    assert 'first name:"Prince"' in script
    assert 'last name:""' in script
    assert 'label:"home"' in script


def test_create_contact_validates_input():
    assert "name cannot be empty" in create_contact("  ", "+15551234567")
    assert "phone cannot be empty" in create_contact("Ada", "  ")


@patch(
    "mac_messages_mcp.messages.run_applescript", return_value="Error: not authorized"
)
def test_create_contact_surfaces_applescript_errors(mock_applescript):
    result = create_contact("Ada", "+15551234567")

    assert "Error creating contact: not authorized" in result


@patch("mac_messages_mcp.messages.run_applescript", return_value="success")
def test_create_contact_escapes_applescript(mock_applescript):
    create_contact('Ada "Countess"', "+15551234567")

    script = mock_applescript.call_args[0][0]
    assert 'first name:"Ada"' in script
    assert '\\"Countess\\"' in script


# ---------------------------------------------------------------------------
# Elicitation-backed confirmation
# ---------------------------------------------------------------------------


class _FakeContext:
    def __init__(self, approval=None, error=None):
        self.approval = approval
        self.error = error
        self.elicited: str | None = None

    async def elicit(self, message, schema):
        self.elicited = message
        if self.error is not None:
            raise self.error
        return self.approval


def _approval(action, approve=None):
    return SimpleNamespace(
        action=action,
        data=None if approve is None else SimpleNamespace(approve=approve),
    )


def test_send_tool_confirmed_send_proceeds_after_accept():
    ctx = _FakeContext(_approval("accept", True))
    with patch("mac_messages_mcp.server.send_message", return_value="SENT") as send:
        result = asyncio.run(
            tool_send_message(
                recipient="+15551234567",
                message="hi",
                confirm=True,
                ctx=ctx,
            ),
        )

    assert "SENT" in result
    assert ctx.elicited is not None
    send.assert_called_once()
    assert send.call_args.kwargs["recipient"] == "+15551234567"


def test_send_tool_confirmed_send_stops_on_decline():
    ctx = _FakeContext(_approval("decline"))
    with patch("mac_messages_mcp.server.send_message") as send:
        result = asyncio.run(
            tool_send_message(
                recipient="+15551234567",
                message="hi",
                confirm=True,
                ctx=ctx,
            ),
        )

    assert "cancelled" in result.lower()
    send.assert_not_called()


def test_send_tool_confirmed_send_stops_when_user_unchecks_approval():
    ctx = _FakeContext(_approval("accept", False))
    with patch("mac_messages_mcp.server.send_message") as send:
        result = asyncio.run(
            tool_send_message(
                recipient="+15551234567",
                message="hi",
                confirm=True,
                ctx=ctx,
            ),
        )

    assert "cancelled" in result.lower()
    send.assert_not_called()


def test_send_tool_without_context_refuses_instead_of_sending():
    with patch("mac_messages_mcp.server.send_message") as send:
        result = asyncio.run(
            tool_send_message(
                recipient="+15551234567",
                message="hi",
                confirm=True,
            ),
        )

    assert "no MCP request context" in result
    send.assert_not_called()


def test_send_tool_refuses_when_elicitation_is_unsupported():
    ctx = _FakeContext(error=RuntimeError("client has no elicitation"))
    with patch("mac_messages_mcp.server.send_message") as send:
        result = asyncio.run(
            tool_send_message(
                recipient="+15551234567",
                message="hi",
                confirm=True,
                ctx=ctx,
            ),
        )

    assert "could not ask the user to confirm" in result
    assert "nothing was sent" in result
    send.assert_not_called()


def test_send_tool_defaults_to_sending_without_asking():
    with patch("mac_messages_mcp.server.send_message", return_value="sent") as send:
        result = asyncio.run(tool_send_message(recipient="+15551234567", message="hi"))

    assert "sent" in result
    send.assert_called_once()
    assert "attachment_paths" in send.call_args.kwargs


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def test_schedule_list_and_cancel_round_trip():
    try:
        created = tool_schedule_message(
            recipient="+15551234567",
            message="later",
            send_at="2099-01-01T00:00:00+00:00",
        )
        assert "Scheduled msg-" in created
        match = re.search(r"msg-\d+", created)
        assert match is not None
        job_id = match.group(0)

        listing = tool_list_scheduled_messages()
        assert job_id in listing
        assert "pending" in listing

        assert "Cancelled scheduled message" in tool_cancel_scheduled_message(job_id)
        assert "No pending scheduled message" in tool_cancel_scheduled_message(job_id)
    finally:
        scheduler.stop()


def test_schedule_rejects_a_bad_timestamp():
    result = tool_schedule_message(
        recipient="+15551234567",
        message="later",
        send_at="tomorrow",
    )

    assert "send_at must be an ISO 8601 timestamp" in result


def test_schedule_rejects_empty_content():
    result = tool_schedule_message(
        recipient="+15551234567",
        message="",
        send_at="2099-01-01T00:00:00+00:00",
    )

    assert "Error scheduling message" in result


def test_cancel_of_unknown_job_is_reported():
    assert "No pending scheduled message with id msg-absent" in (
        tool_cancel_scheduled_message("msg-absent")
    )


# ---------------------------------------------------------------------------
# Server wiring
# ---------------------------------------------------------------------------


def test_list_conversations_tool_delegates():
    with patch(
        "mac_messages_mcp.server.list_conversations",
        return_value="CONVERSATIONS",
    ) as delegate:
        result = tool_list_conversations(limit=5, unread_only=True)

    assert "CONVERSATIONS" in result
    delegate.assert_called_once_with(limit=5, unread_only=True)


def test_wait_tool_delegates():
    with patch(
        "mac_messages_mcp.server.wait_for_new_messages",
        return_value="WAITED",
    ) as delegate:
        result = tool_wait_for_new_messages(since_rowid=3, timeout_seconds=2)

    assert "WAITED" in result
    delegate.assert_called_once_with(
        since_rowid=3,
        timeout_seconds=2,
        poll_interval=1.0,
        contact=None,
        chat_id=None,
    )


def test_search_attachment_contents_tool_passes_filters():
    with patch(
        "mac_messages_mcp.server.search_attachment_contents",
        return_value="FOUND",
    ) as delegate:
        result = tool_search_attachment_contents(
            "invoice",
            mime_type="application/pdf",
            limit=3,
        )

    assert "FOUND" in result
    delegate.assert_called_once_with(
        "invoice",
        start_date=None,
        end_date=None,
        contact=None,
        mime_type="application/pdf",
        limit=3,
        max_file_bytes=2_000_000,
    )


def test_create_contact_tool_delegates():
    with patch(
        "mac_messages_mcp.server.create_contact",
        return_value="CREATED",
    ) as delegate:
        result = tool_create_contact("Ada", "+15551234567", label="home")

    assert "CREATED" in result
    delegate.assert_called_once_with(name="Ada", phone="+15551234567", label="home")


def test_prompts_reference_the_tools_they_need():
    assert "tool_list_conversations" in triage_unread_messages()
    assert "tool_get_recent_messages" in triage_unread_messages()
    assert "hours=12" in summarize_recent_messages(12)
    assert "Ada" in draft_reply("Ada")
    assert "tool_send_message" in draft_reply("Ada")
