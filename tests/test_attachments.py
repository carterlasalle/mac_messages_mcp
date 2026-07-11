"""
Tests for attachment finding and download.

Style follows the rest of the suite: unittest + mocking. We patch
query_messages_db to return canned attachment rows and assert that
filtering, formatting, and progressive-disclosure behaviours all work.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from mac_messages_mcp.messages import (
    _attachments_for_message_ids,
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
    mime_type="image/heic",
    uti="public.heic",
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


class TestFilterExcludedAttachments(unittest.TestCase):
    """The filter that drops plugin payloads and stickers by default."""

    def test_keeps_normal_image(self):
        rows = [make_attachment_row(mime_type="image/jpeg", uti="public.jpeg")]
        kept = _filter_excluded_attachments(rows)
        self.assertEqual(len(kept), 1)

    def test_drops_sticker(self):
        rows = [make_attachment_row(is_sticker=1)]
        self.assertEqual(_filter_excluded_attachments(rows), [])

    def test_drops_plugin_payload_uti(self):
        rows = [
            make_attachment_row(
                uti="com.apple.messages.MSMessageExtensionBalloonPlugin",
                mime_type=None,
            )
        ]
        self.assertEqual(_filter_excluded_attachments(rows), [])

    def test_drops_pluginpayloadattachment_filename(self):
        rows = [
            make_attachment_row(
                transfer_name="payload.pluginPayloadAttachment",
                uti=None,
            )
        ]
        self.assertEqual(_filter_excluded_attachments(rows), [])

    def test_keeps_pdf(self):
        rows = [
            make_attachment_row(
                mime_type="application/pdf",
                uti="com.adobe.pdf",
                transfer_name="letter.pdf",
            )
        ]
        self.assertEqual(len(_filter_excluded_attachments(rows)), 1)


class TestAttachmentsForMessageIds(unittest.TestCase):
    """Tier 1 helper: lookup attachments for a given list of message ROWIDs."""

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_empty_input_short_circuits(self, mock_query):
        result = _attachments_for_message_ids([])
        self.assertEqual(result, {})
        mock_query.assert_not_called()

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_groups_by_message_id(self, mock_query):
        mock_query.return_value = [
            make_attachment_row(rowid=1, message_id=10, mime_type="image/jpeg"),
            make_attachment_row(rowid=2, message_id=10, mime_type="image/png"),
            make_attachment_row(rowid=3, message_id=20, mime_type="application/pdf"),
        ]
        result = _attachments_for_message_ids([10, 20])
        self.assertEqual(set(result.keys()), {10, 20})
        self.assertEqual(len(result[10]), 2)
        self.assertEqual(len(result[20]), 1)
        self.assertEqual(result[10][0]["mime_type"], "image/jpeg")

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_filters_excluded_in_default(self, mock_query):
        mock_query.return_value = [
            make_attachment_row(rowid=1, message_id=10, mime_type="image/jpeg"),
            make_attachment_row(rowid=2, message_id=10, is_sticker=1),
        ]
        result = _attachments_for_message_ids([10])
        self.assertEqual(len(result[10]), 1)
        self.assertEqual(result[10][0]["id"], 1)

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_message_with_no_attachments_absent_from_dict(self, mock_query):
        mock_query.return_value = []
        result = _attachments_for_message_ids([10, 20])
        self.assertEqual(result, {})

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_db_error_returns_empty_dict(self, mock_query):
        mock_query.return_value = [{"error": "no full disk access"}]
        result = _attachments_for_message_ids([10])
        self.assertEqual(result, {})


class TestSearchAttachments(unittest.TestCase):
    """Tier 2 tool: top-level attachment search returning formatted text."""

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_no_results_message(self, mock_query):
        mock_query.return_value = []
        result = search_attachments()
        self.assertIn("No attachments found", result)

    @patch("mac_messages_mcp.messages.os.path.exists", return_value=True)
    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Elizabeth")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_formats_attachment_metadata(self, mock_query, _name, _exists):
        mock_query.return_value = [
            make_attachment_row(
                rowid=42,
                message_id=10,
                mime_type="image/jpeg",
                transfer_name="invitation.jpg",
                total_bytes=98_765,
            ),
        ]
        result = search_attachments()
        self.assertIn("42", result)  # attachment id is referenceable
        self.assertIn("image/jpeg", result)  # mime type shown
        self.assertIn("invitation.jpg", result)  # transfer_name shown

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_mime_type_filter_param_is_passed_to_query(self, mock_query):
        mock_query.return_value = []
        search_attachments(mime_type="image/")
        call_args = mock_query.call_args
        sql, params = call_args[0]
        # The implementation should LIKE-match on mime_type
        self.assertIn("mime_type", sql.lower())
        self.assertIn("image/%", params)

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_date_range_params_passed(self, mock_query):
        mock_query.return_value = []
        search_attachments(start_date="2026-04-01", end_date="2026-04-30")
        call_args = mock_query.call_args
        sql, params = call_args[0]
        # Two timestamp params (start, end) + any others
        # Apple ns timestamps should be ints in params
        self.assertTrue(
            any(isinstance(p, int) and p > 0 for p in params),
            f"Expected an Apple-ns int in params: {params}",
        )

    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Someone")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_limit_caps_results(self, mock_query, _name):
        mock_query.return_value = [
            make_attachment_row(rowid=i, message_id=10 + i, mime_type="image/jpeg")
            for i in range(50)
        ]
        result = search_attachments(limit=10)
        # Only 10 rows shown
        self.assertEqual(result.count("image/jpeg"), 10)

    @patch("mac_messages_mcp.messages.os.path.exists", return_value=False)
    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Someone")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_marks_missing_files_but_keeps_them(self, mock_query, _name, _exists):
        mock_query.return_value = [
            make_attachment_row(rowid=42, mime_type="image/jpeg"),
        ]
        result = search_attachments()
        self.assertIn("42", result)
        self.assertIn("missing", result.lower())


class TestGetAttachment(unittest.TestCase):
    """Tier 3 tool: fetch a single attachment by id."""

    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_unknown_id_returns_error(self, mock_query):
        mock_query.return_value = []
        result = get_attachment(99999)
        self.assertIsInstance(result, str)
        self.assertIn("not found", result.lower())

    @patch("mac_messages_mcp.messages.os.path.exists", return_value=False)
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_missing_on_disk_returns_path_with_warning(self, mock_query, _exists):
        mock_query.return_value = [
            make_attachment_row(rowid=42, mime_type="image/jpeg")
        ]
        result = get_attachment(42)
        self.assertIsInstance(result, str)
        self.assertIn("missing", result.lower())

    @patch("mac_messages_mcp.messages.os.path.getsize", return_value=200)
    @patch("mac_messages_mcp.messages.os.path.exists", return_value=True)
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_pdf_returns_path_metadata_text(self, mock_query, _exists, _size):
        mock_query.return_value = [
            make_attachment_row(
                rowid=42,
                mime_type="application/pdf",
                transfer_name="letter.pdf",
                uti="com.adobe.pdf",
            )
        ]
        result = get_attachment(42)
        # PDF → string (path metadata), not an Image
        self.assertIsInstance(result, str)
        self.assertIn("letter.pdf", result)
        self.assertIn("application/pdf", result)
        # Path returned for caller to Read
        self.assertIn("/Library/Messages/Attachments/", result)

    @patch("mac_messages_mcp.messages.os.path.getsize", return_value=10_000_000)
    @patch("mac_messages_mcp.messages.os.path.exists", return_value=True)
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_oversize_image_falls_back_to_path(self, mock_query, _exists, _size):
        mock_query.return_value = [
            make_attachment_row(
                rowid=42,
                mime_type="image/jpeg",
                transfer_name="big.jpg",
                total_bytes=10_000_000,
            )
        ]
        result = get_attachment(42, max_bytes=5_000_000)
        # Path-only string return (no inline bytes), but path must still be there
        self.assertIsInstance(result, str)
        self.assertIn("max_bytes", result.lower())
        self.assertIn("big.jpg", result)
        self.assertIn("path:", result)
        self.assertIn("/Library/Messages/Attachments/", result)

    @patch("mac_messages_mcp.messages.os.path.getsize", return_value=200)
    @patch("mac_messages_mcp.messages.os.path.exists", return_value=True)
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_jpeg_returns_path_and_image(self, mock_query, _exists, _size):
        """Always-path contract: inline image returns BOTH path metadata AND inline bytes."""
        # One-pixel valid JPEG
        jpeg_bytes = bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb0043000806060706050806070707"
            "09090808" + "0a" * 50 + "ffd9"
        )
        with patch("builtins.open", unittest.mock.mock_open(read_data=jpeg_bytes)):
            mock_query.return_value = [
                make_attachment_row(
                    rowid=42,
                    mime_type="image/jpeg",
                    transfer_name="photo.jpg",
                    total_bytes=200,
                )
            ]
            result = get_attachment(42)
        # Returns a list: [metadata_text, Image]
        from mcp.server.fastmcp import Image

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        text = next((x for x in result if isinstance(x, str)), None)
        img = next((x for x in result if isinstance(x, Image)), None)
        self.assertIsNotNone(text, "Expected path metadata string in result")
        self.assertIsNotNone(img, "Expected inline Image in result")
        # The path must be present in the text so the human can act on the file
        self.assertIn("path:", text)
        self.assertIn("photo.jpg", text)
        self.assertIn("/Library/Messages/Attachments/", text)


class TestFormatAttachmentSummary(unittest.TestCase):
    """The compact one-line summary appended to message lines (Tier 1)."""

    def test_empty_returns_empty_string(self):
        self.assertEqual(_format_attachment_summary([]), "")

    def test_single_attachment(self):
        line = _format_attachment_summary(
            [
                {"id": 42, "mime_type": "image/jpeg", "filename": "photo.jpg"},
            ]
        )
        # Should mention id and mime_type at minimum so agent can call get_attachment
        self.assertIn("42", line)
        self.assertIn("image/jpeg", line)

    def test_multiple_attachments_short(self):
        line = _format_attachment_summary(
            [
                {"id": 1, "mime_type": "image/jpeg", "filename": "a.jpg"},
                {"id": 2, "mime_type": "image/heic", "filename": "b.heic"},
            ]
        )
        # Both ids surface
        self.assertIn("1", line)
        self.assertIn("2", line)
        # Sanity: small token cost — well under 200 chars for two attachments
        self.assertLess(len(line), 200)


class TestGetRecentMessagesAttachmentAugmentation(unittest.TestCase):
    """Tier 1: tool_get_recent_messages should annotate messages that have attachments."""

    @patch("mac_messages_mcp.messages._attachments_for_message_ids")
    @patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Elizabeth")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_appends_attachment_summary(self, mock_query, _name, _mapping, mock_atts):
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
        result = get_recent_messages(hours=24)
        # Message 100 line should mention attachment id 42
        self.assertIn("42", result)
        self.assertIn("image/jpeg", result)
        # Message 101 line should still appear, without an attachment marker
        self.assertIn("see you Saturday", result)

    @patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
    @patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Elizabeth")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_no_attachments_does_not_change_existing_format(
        self, mock_query, _name, _mapping, _atts
    ):
        """Backwards-compat: when no message has attachments, output is exactly the old format."""
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
        self.assertIn("hello", result)
        # No attachment-related text leaks in
        self.assertNotIn("attachment", result.lower())
        self.assertNotIn("📎", result)


class TestFuzzySearchAttachmentAugmentation(unittest.TestCase):
    """Tier 1: tool_fuzzy_search_messages should annotate messages that have attachments."""

    @patch("mac_messages_mcp.messages._attachments_for_message_ids")
    @patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Elizabeth")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_appends_attachment_summary(self, mock_query, _name, _mapping, mock_atts):
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
        result = fuzzy_search_messages("birthday", hours=24, threshold=0.5)
        self.assertIn("7", result)
        self.assertIn("image/heic", result)


if __name__ == "__main__":
    unittest.main()
