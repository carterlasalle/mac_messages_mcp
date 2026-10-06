# Copyright (c) 2023 Carter Lasalle
"""Tests for attachment finding and download.

Style follows the rest of the suite: pytest-style functions with mocking. We
patch query_messages_db to return canned attachment rows and assert that
filtering, formatting, and progressive-disclosure behaviours all work.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from mac_messages_mcp.messages import (
    _attachments_for_message_ids,
    _describe_attachment,
    _filter_excluded_attachments,
    _format_attachment_summary,
    fuzzy_search_messages,
    get_attachment,
    get_recent_messages,
    search_attachments,
)


def make_attachment_row(
    rowid=1,
    message_id=10,
    filename="~/Library/Messages/Attachments/aa/00/IMG_1234.heic",
    transfer_name="IMG_1234.heic",
    mime_type: str | None = "image/heic",
    uti: str | None = "public.heic",
    total_bytes=1024,
    is_sticker=0,
    hide_attachment=0,
    created_date=700_000_000_000_000_000,  # Apple epoch ns
    message_date=700_000_000_000_000_000,
    is_from_me=0,
    handle_id=99,
):
    """Build a SQLite Row-style dict mimicking the JOIN we'll run."""
    return {
        "attachment_id": rowid,
        "message_id": message_id,
        "filename": filename,
        "transfer_name": transfer_name,
        "mime_type": mime_type,
        "uti": uti,
        "total_bytes": total_bytes,
        "is_sticker": is_sticker,
        "hide_attachment": hide_attachment,
        "created_date": created_date,
        "message_date": message_date,
        "is_from_me": is_from_me,
        "handle_id": handle_id,
    }


# The filter that drops plugin payloads and stickers by default.


def test_keeps_normal_image():
    rows = [make_attachment_row(mime_type="image/jpeg", uti="public.jpeg")]
    kept = _filter_excluded_attachments(rows)
    assert len(kept) == 1


def test_drops_sticker():
    rows = [make_attachment_row(is_sticker=1)]
    assert not _filter_excluded_attachments(rows)


def test_drops_plugin_payload_uti():
    rows = [
        make_attachment_row(
            uti="com.apple.messages.MSMessageExtensionBalloonPlugin",
            mime_type=None,
        ),
    ]
    assert not _filter_excluded_attachments(rows)


def test_drops_pluginpayloadattachment_filename():
    rows = [
        make_attachment_row(
            transfer_name="payload.pluginPayloadAttachment",
            uti=None,
        ),
    ]
    assert not _filter_excluded_attachments(rows)


def test_keeps_pdf():
    rows = [
        make_attachment_row(
            mime_type="application/pdf",
            uti="com.adobe.pdf",
            transfer_name="letter.pdf",
        ),
    ]
    assert len(_filter_excluded_attachments(rows)) == 1


# Tier 1 helper: lookup attachments for a given list of message ROWIDs.


@patch("mac_messages_mcp.messages.query_messages_db")
def test_empty_input_short_circuits(mock_query):
    result = _attachments_for_message_ids([])
    assert not result
    mock_query.assert_not_called()


@patch("mac_messages_mcp.messages.query_messages_db")
def test_groups_by_message_id(mock_query):
    mock_query.return_value = [
        make_attachment_row(rowid=1, message_id=10, mime_type="image/jpeg"),
        make_attachment_row(rowid=2, message_id=10, mime_type="image/png"),
        make_attachment_row(rowid=3, message_id=20, mime_type="application/pdf"),
    ]
    result = _attachments_for_message_ids([10, 20])
    assert set(result.keys()) == {10, 20}
    assert len(result[10]) == 2
    assert len(result[20]) == 1
    assert result[10][0]["mime_type"] == "image/jpeg"


@patch("mac_messages_mcp.messages.query_messages_db")
def test_filters_excluded_in_default(mock_query):
    mock_query.return_value = [
        make_attachment_row(rowid=1, message_id=10, mime_type="image/jpeg"),
        make_attachment_row(rowid=2, message_id=10, is_sticker=1),
    ]
    result = _attachments_for_message_ids([10])
    assert len(result[10]) == 1
    assert result[10][0]["id"] == 1


@patch("mac_messages_mcp.messages.query_messages_db")
def test_message_with_no_attachments_absent_from_dict(mock_query):
    mock_query.return_value = []
    result = _attachments_for_message_ids([10, 20])
    assert not result


@patch("mac_messages_mcp.messages.query_messages_db")
def test_db_error_returns_empty_dict(mock_query):
    mock_query.return_value = [{"error": "no full disk access"}]
    result = _attachments_for_message_ids([10])
    assert not result


# Tier 2 tool: top-level attachment search returning formatted text.


@patch("mac_messages_mcp.messages.query_messages_db")
def test_no_results_message(mock_query):
    mock_query.return_value = []
    result = search_attachments()
    assert "No attachments found" in result


@patch("mac_messages_mcp.messages.get_contact_name", return_value="Elizabeth")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_formats_attachment_metadata(mock_query, *_):
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp) / "invitation.jpg"
        attachment.write_bytes(b"\xff\xd8\xff\xd9")
        mock_query.return_value = [
            make_attachment_row(
                rowid=42,
                message_id=10,
                filename=str(attachment),
                mime_type="image/jpeg",
                transfer_name="invitation.jpg",
                total_bytes=98_765,
            ),
        ]
        result = search_attachments()
    assert "42" in result  # attachment id is referenceable
    assert "image/jpeg" in result  # mime type shown
    assert "invitation.jpg" in result  # transfer_name shown


@patch("mac_messages_mcp.messages.query_messages_db")
def test_mime_type_filter_param_is_passed_to_query(mock_query):
    mock_query.return_value = []
    search_attachments(mime_type="image/")
    call_args = mock_query.call_args
    sql, params = call_args[0]
    # The implementation should LIKE-match on mime_type
    assert "mime_type" in sql.lower()
    assert "image/%" in params


@patch("mac_messages_mcp.messages.query_messages_db")
def test_date_range_params_passed(mock_query):
    mock_query.return_value = []
    search_attachments(start_date="2026-04-01", end_date="2026-04-30")
    call_args = mock_query.call_args
    _sql, params = call_args[0]
    # Two timestamp params (start, end) + any others
    # Apple ns timestamps should be ints in params
    assert any(
        isinstance(p, int) and p > 0 for p in params
    ), f"Expected an Apple-ns int in params: {params}"


@patch("mac_messages_mcp.messages.get_contact_name", return_value="Someone")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_limit_caps_results(mock_query, *_):
    mock_query.return_value = [
        make_attachment_row(rowid=i, message_id=10 + i, mime_type="image/jpeg")
        for i in range(50)
    ]
    result = search_attachments(limit=10)
    # Only 10 rows shown
    assert result.count("image/jpeg") == 10


@patch("mac_messages_mcp.messages.query_messages_db")
def test_marks_missing_files_but_keeps_them(mock_query, tmp_path):
    missing = tmp_path / "missing.jpg"
    row = make_attachment_row(rowid=42, mime_type="image/jpeg")
    row["filename"] = str(missing)
    mock_query.return_value = [row]
    with patch("mac_messages_mcp.messages.get_contact_name", return_value="Someone"):
        result = search_attachments()
    assert "42" in result
    assert "missing" in result.lower()


# Tier 3 tool: fetch a single attachment by id.


@patch("mac_messages_mcp.messages.query_messages_db")
def test_unknown_id_returns_error(mock_query):
    mock_query.return_value = []
    result = get_attachment(99999)
    assert isinstance(result, str)
    assert "not found" in result.lower()


@patch("mac_messages_mcp.messages.query_messages_db")
def test_missing_on_disk_returns_path_with_warning(mock_query, tmp_path):
    missing = tmp_path / "missing.jpg"
    row = make_attachment_row(rowid=42, mime_type="image/jpeg")
    row["filename"] = str(missing)
    mock_query.return_value = [row]
    result = get_attachment(42)
    assert isinstance(result, str)
    assert "missing" in result.lower()


@patch("mac_messages_mcp.messages.query_messages_db")
def test_pdf_returns_path_metadata_text(mock_query):
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp) / "letter.pdf"
        attachment.write_bytes(b"%PDF-1.4\n")
        mock_query.return_value = [
            make_attachment_row(
                rowid=42,
                filename=str(attachment),
                mime_type="application/pdf",
                transfer_name="letter.pdf",
                uti="com.adobe.pdf",
            ),
        ]
        result = get_attachment(42)
    # PDF → string (path metadata), not an Image
    assert isinstance(result, str)
    assert "letter.pdf" in result
    assert "application/pdf" in result
    # Path returned for caller to Read
    assert str(attachment) in result


@patch("mac_messages_mcp.messages.query_messages_db")
def test_oversize_image_falls_back_to_path(mock_query):
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp) / "big.jpg"
        attachment.write_bytes(b"\xff" * 200)
        mock_query.return_value = [
            make_attachment_row(
                rowid=42,
                filename=str(attachment),
                mime_type="image/jpeg",
                transfer_name="big.jpg",
                total_bytes=10_000_000,
            ),
        ]
        result = get_attachment(42, max_bytes=100)
    # Path-only string return (no inline bytes), but path must still be there
    assert isinstance(result, str)
    assert "max_bytes" in result.lower()
    assert "big.jpg" in result
    assert "path:" in result
    assert str(attachment) in result


@patch("mac_messages_mcp.messages.query_messages_db")
def test_jpeg_returns_path_and_image(mock_query):
    """Always-path contract: inline image returns path metadata AND inline bytes."""
    from mcp.server.fastmcp import Image

    # One-pixel valid JPEG
    jpeg_bytes = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb0043000806060706050806070707"
        "09090808" + "0a" * 50 + "ffd9",
    )
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp) / "photo.jpg"
        attachment.write_bytes(jpeg_bytes)
        mock_query.return_value = [
            make_attachment_row(
                rowid=42,
                filename=str(attachment),
                mime_type="image/jpeg",
                transfer_name="photo.jpg",
                total_bytes=200,
            ),
        ]
        result = get_attachment(42)
    # Returns a list: [metadata_text, Image]
    assert isinstance(result, list)
    assert len(result) == 2
    text = next((x for x in result if isinstance(x, str)), None)
    img = next((x for x in result if isinstance(x, Image)), None)
    assert text is not None, "Expected path metadata string in result"
    assert img is not None, "Expected inline Image in result"
    # The path must be present in the text so the human can act on the file
    assert "path:" in text
    assert "photo.jpg" in text
    assert str(attachment) in text


@patch("mac_messages_mcp.messages.query_messages_db")
def test_describe_attachment_returns_summary_and_path(mock_query, tmp_path):
    attachment = tmp_path / "invitation.pdf"
    attachment.write_bytes(b"%PDF-1.4\n")
    mock_query.return_value = [
        make_attachment_row(
            rowid=42,
            filename=str(attachment),
            mime_type="application/pdf",
            transfer_name="invitation.pdf",
            total_bytes=9,
        ),
    ]

    summary, path = _describe_attachment(42)

    assert path == str(attachment)
    assert "invitation.pdf" in summary
    assert str(attachment) in summary


@patch("mac_messages_mcp.messages.query_messages_db")
def test_describe_attachment_missing_file_has_no_path(mock_query, tmp_path):
    missing = tmp_path / "missing.jpg"
    mock_query.return_value = [
        make_attachment_row(
            rowid=42, filename=str(missing), transfer_name="missing.jpg"
        ),
    ]

    summary, path = _describe_attachment(42)

    assert path is None
    assert "missing on disk" in summary


@patch("mac_messages_mcp.messages.query_messages_db")
def test_describe_attachment_unknown_id_has_no_path(mock_query):
    mock_query.return_value = []

    summary, path = _describe_attachment(99999)

    assert path is None
    assert "not found" in summary.lower()


# The compact one-line summary appended to message lines (Tier 1).


def test_empty_returns_empty_string():
    assert not _format_attachment_summary([])


def test_single_attachment():
    line = _format_attachment_summary(
        [
            {"id": 42, "mime_type": "image/jpeg", "filename": "photo.jpg"},
        ],
    )
    # Should mention id and mime_type at minimum so agent can call get_attachment
    assert "42" in line
    assert "image/jpeg" in line


def test_multiple_attachments_short():
    line = _format_attachment_summary(
        [
            {"id": 1, "mime_type": "image/jpeg", "filename": "a.jpg"},
            {"id": 2, "mime_type": "image/heic", "filename": "b.heic"},
        ],
    )
    # Both ids surface
    assert "1" in line
    assert "2" in line
    # Sanity: small token cost — well under 200 chars for two attachments
    assert len(line) < 200


# Tier 1: tool_get_recent_messages should annotate messages that have attachments.


@patch("mac_messages_mcp.messages._attachments_for_message_ids")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_appends_attachment_summary_to_recent_messages(mock_query, mock_atts):
    # Two messages: one with an attachment, one without
    mock_query.return_value = [
        {
            "ROWID": 100,
            "date": 700_000_000_000_000_000,
            "text": "here's the invitation",
            "attributedBody": None,
            "is_from_me": 0,
            "handle_id": 99,
            "cache_roomnames": None,
        },
        {
            "ROWID": 101,
            "date": 700_000_000_000_000_001,
            "text": "see you Saturday",
            "attributedBody": None,
            "is_from_me": 0,
            "handle_id": 99,
            "cache_roomnames": None,
        },
    ]
    mock_atts.return_value = {
        100: [{"id": 42, "mime_type": "image/jpeg", "filename": "invite.jpg"}],
    }
    with (
        patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        patch("mac_messages_mcp.messages.get_contact_name", return_value="Elizabeth"),
    ):
        result = get_recent_messages(hours=24)
    # Message 100 line should mention attachment id 42
    assert "42" in result
    assert "image/jpeg" in result
    # Message 101 line should still appear, without an attachment marker
    assert "see you Saturday" in result


@patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
@patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
@patch("mac_messages_mcp.messages.get_contact_name", return_value="Elizabeth")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_no_attachments_does_not_change_existing_format(mock_query, *_):
    """Backwards-compat: with no attachments, output is exactly the old format."""
    mock_query.return_value = [
        {
            "ROWID": 100,
            "date": 700_000_000_000_000_000,
            "text": "hello",
            "attributedBody": None,
            "is_from_me": 1,
            "handle_id": 99,
            "cache_roomnames": None,
        },
    ]
    result = get_recent_messages(hours=24)
    assert "hello" in result
    # No attachment-related text leaks in
    assert "attachment" not in result.lower()
    assert "📎" not in result


# Tier 1: tool_fuzzy_search_messages should annotate messages that have attachments.


@patch("mac_messages_mcp.messages._attachments_for_message_ids")
@patch("mac_messages_mcp.messages.query_messages_db")
def test_appends_attachment_summary_to_fuzzy_search(mock_query, mock_atts):
    mock_query.return_value = [
        {
            "ROWID": 100,
            "date": 700_000_000_000_000_000,
            "text": "Lowen birthday party invitation",
            "attributedBody": None,
            "is_from_me": 0,
            "handle_id": 99,
            "cache_roomnames": None,
        },
    ]
    mock_atts.return_value = {
        100: [{"id": 7, "mime_type": "image/heic", "filename": "lowen.heic"}],
    }
    with (
        patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        patch("mac_messages_mcp.messages.get_contact_name", return_value="Elizabeth"),
    ):
        result = fuzzy_search_messages("birthday", hours=24, threshold=0.5)
    assert "7" in result
    assert "image/heic" in result
