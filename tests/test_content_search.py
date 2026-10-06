# Copyright (c) 2023 Carter Lasalle
"""Tests for attachment *content* search.

Style follows the rest of the suite: pytest functions with ``unittest.mock``.
``query_messages_db`` is patched to return canned attachment-join rows, and
attachment files live under ``tmp_path`` so nothing touches the real database
or the network.
"""

from pathlib import Path
from unittest.mock import patch

from mac_messages_mcp.content import search_attachment_contents


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


@patch("mac_messages_mcp.messages.query_messages_db")
def test_text_file_match_returns_id_and_snippet(mock_query, tmp_path):
    body = "alpha bravo NEEDLE charlie " + ("padding " * 40)
    note = tmp_path / "note.txt"
    note.write_text(body, encoding="utf-8")
    mock_query.return_value = [
        make_attachment_row(
            rowid=7,
            message_id=42,
            filename=str(note),
            transfer_name="note.txt",
            mime_type="text/plain",
            uti="public.plain-text",
        ),
    ]

    result = search_attachment_contents("needle")

    assert "Found 1 attachment(s) containing 'needle':" in result
    assert "#7" in result
    assert "note.txt" in result
    assert "NEEDLE" in result
    assert "..." in result


@patch("mac_messages_mcp.messages.query_messages_db")
def test_non_matching_query_reports_no_match(mock_query, tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("nothing interesting here", encoding="utf-8")
    mock_query.return_value = [
        make_attachment_row(
            filename=str(note),
            transfer_name="note.txt",
            mime_type="text/plain",
            uti="public.plain-text",
        ),
    ]

    result = search_attachment_contents("absent")

    expected = "No attachment contents matched 'absent' in 1 scanned attachment(s)."
    assert expected in result


def test_empty_query_rejected():
    assert "Error: query cannot be empty." in search_attachment_contents("   ")


def test_non_positive_limit_rejected():
    assert "Error: limit must be positive." in search_attachment_contents(
        "x",
        limit=0,
    )


def test_bad_start_date_rejected():
    result = search_attachment_contents("x", start_date="2024-13-01")
    assert "Error: start_date must be YYYY-MM-DD, got '2024-13-01'." in result


def test_bad_end_date_rejected():
    result = search_attachment_contents("x", end_date="garbage")
    assert "Error: end_date must be YYYY-MM-DD, got 'garbage'." in result


@patch("mac_messages_mcp.messages.query_messages_db")
def test_missing_file_counted_and_not_fatal(mock_query, tmp_path):
    missing = tmp_path / "gone.txt"
    mock_query.return_value = [
        make_attachment_row(
            filename=str(missing),
            transfer_name="gone.txt",
            mime_type="text/plain",
            uti="public.plain-text",
        ),
    ]

    result = search_attachment_contents("needle")

    assert "No attachment contents matched" in result
    assert "1 missing file(s)" in result


@patch("mac_messages_mcp.messages.query_messages_db")
def test_unsupported_mime_counted(mock_query, tmp_path):
    blob = tmp_path / "archive.zip"
    blob.write_bytes(b"PK\x03\x04 needle inside a zip")
    mock_query.return_value = [
        make_attachment_row(
            filename=str(blob),
            transfer_name="archive.zip",
            mime_type="application/zip",
            uti="public.zip-archive",
        ),
    ]

    result = search_attachment_contents("needle")

    assert "No attachment contents matched" in result
    assert "1 unsupported type(s)" in result
    assert "Found" not in result


@patch("mac_messages_mcp.messages.query_messages_db")
def test_unreadable_file_counted_and_not_fatal(mock_query, tmp_path):
    # A directory named like a text file: exists() is True but open() raises
    # IsADirectoryError (an OSError), which must be swallowed and counted.
    weird = tmp_path / "weird.txt"
    weird.mkdir()
    mock_query.return_value = [
        make_attachment_row(
            filename=str(weird),
            transfer_name="weird.txt",
            mime_type="text/plain",
            uti="public.plain-text",
        ),
    ]

    result = search_attachment_contents("needle")

    assert "1 unreadable file(s)" in result


@patch("mac_messages_mcp.messages.query_messages_db")
def test_limit_caps_matches(mock_query, tmp_path):
    rows = []
    for i in range(3):
        doc = tmp_path / f"doc{i}.txt"
        doc.write_text(f"needle number {i}", encoding="utf-8")
        rows.append(
            make_attachment_row(
                rowid=i + 1,
                message_id=100 + i,
                filename=str(doc),
                transfer_name=f"doc{i}.txt",
                mime_type="text/plain",
                uti="public.plain-text",
            ),
        )
    mock_query.return_value = rows

    result = search_attachment_contents("needle", limit=2)

    assert "Found 2 attachment(s) containing 'needle':" in result
    assert result.count("(message #") == 2
    # SQL LIMIT is the overshoot bound (limit * 5), not the match cap.
    assert mock_query.call_args[0][1][-1] == 10


@patch("mac_messages_mcp.messages.query_messages_db")
def test_db_error_surfaces(mock_query):
    mock_query.return_value = [{"error": "disk error"}]

    result = search_attachment_contents("needle")

    assert "Error querying attachments: disk error" in result
