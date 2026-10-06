# Copyright (c) 2023 Carter Lasalle
"""Coverage for the read-layer features added on top of get_recent_messages.

These pin the observable behaviour of the per-message metadata tags, paging,
date filters, cursor reads, conversation listing, scoped search, and the
new-message wait. All database access is mocked; no real Messages data is read.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from mac_messages_mcp.messages import (
    _to_apple_ns,
    fuzzy_search_messages,
    get_recent_messages,
    list_conversations,
    wait_for_new_messages,
)

_NOW = datetime.now(timezone.utc)
_APPLE_NOW = _to_apple_ns(_NOW)


def _row(**overrides):
    """One chat.db message row with the columns the read layer selects."""
    row = {
        "ROWID": 100,
        "date": _APPLE_NOW,
        "text": "hello",
        "attributedBody": None,
        "is_from_me": 0,
        "handle_id": 99,
        "cache_roomnames": None,
        "service": None,
        "is_read": None,
        "is_sent": None,
        "is_delivered": None,
        "associated_message_type": None,
        "thread_originator_guid": None,
    }
    row.update(overrides)
    return row


def _read(rows, **kwargs):
    """Call get_recent_messages with every collaborator mocked out."""
    with (
        patch("mac_messages_mcp.messages.query_messages_db", return_value=rows),
        patch(
            "mac_messages_mcp.messages._attachments_for_message_ids", return_value={}
        ),
        patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        patch("mac_messages_mcp.messages.get_contact_name", return_value="Alice"),
    ):
        return get_recent_messages(**kwargs)


# ---------------------------------------------------------------------------
# Metadata tags
# ---------------------------------------------------------------------------


def test_service_and_unread_tags_are_rendered():
    result = _read([_row(service="iMessage", is_read=0)])
    assert "Alice [iMessage] [unread]: hello" in result


def test_read_inbound_message_gets_no_unread_tag():
    result = _read([_row(service="SMS", is_read=1)])
    assert "[unread]" not in result
    assert "[SMS]" in result


def test_undelivered_outbound_is_flagged():
    result = _read(
        [
            _row(
                is_from_me=1,
                is_sent=1,
                is_delivered=0,
                service="iMessage",
                text="outbound",
            ),
        ],
    )
    assert "[iMessage] [not delivered]" in result


def test_tapback_row_renders_reaction_instead_of_being_dropped():
    result = _read(
        [
            _row(
                text=None,
                service="iMessage",
                is_read=1,
                associated_message_type=2001,
            ),
        ],
    )
    assert "[tapback: liked]" in result
    assert "(reaction)" in result


def test_removed_tapback_is_labelled():
    result = _read([_row(text=None, associated_message_type=3003)])
    assert "[tapback: removed laughed]" in result


def test_threaded_reply_is_flagged():
    result = _read([_row(thread_originator_guid="guid:abc")])
    assert "[reply]" in result


def test_unknown_tapback_code_still_renders():
    result = _read([_row(text=None, associated_message_type=2999)])
    assert "[tapback: reaction 2999]" in result


def test_row_without_metadata_columns_is_unchanged():
    row = _row()
    for key in list(row):
        if key in {
            "service",
            "is_read",
            "is_sent",
            "is_delivered",
            "associated_message_type",
            "thread_originator_guid",
        }:
            del row[key]
    result = _read([row])
    assert "Alice: hello" in result
    assert "[" not in result.split("Alice")[1].split(":")[0]


# ---------------------------------------------------------------------------
# Paging, filters, cursor
# ---------------------------------------------------------------------------


def test_limit_caps_rows_and_reports_next_offset():
    rows = [_row(ROWID=1), _row(ROWID=2)]
    result = _read(rows, limit=2)
    assert "offset=2" in result


def test_no_paging_footer_when_under_limit():
    result = _read([_row()], limit=50)
    assert "offset=" not in result


def test_limit_and_offset_bind_to_the_query():
    with patch("mac_messages_mcp.messages.query_messages_db") as mock_query:
        mock_query.return_value = []
        with (
            patch(
                "mac_messages_mcp.messages._attachments_for_message_ids",
                return_value={},
            ),
            patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        ):
            get_recent_messages(hours=1, limit=7, offset=3)
    params = mock_query.call_args[0][1]
    assert params[-2:] == (7, 3)


def test_invalid_limit_and_offset_are_rejected():
    assert "limit must be positive" in get_recent_messages(limit=0)
    assert "at most 1000" in get_recent_messages(limit=1001)
    assert "offset cannot be negative" in get_recent_messages(offset=-1)
    assert "since_rowid cannot be negative" in get_recent_messages(since_rowid=-1)


def test_unread_only_filters_in_sql():
    with patch("mac_messages_mcp.messages.query_messages_db") as mock_query:
        mock_query.return_value = []
        with (
            patch(
                "mac_messages_mcp.messages._attachments_for_message_ids",
                return_value={},
            ),
            patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        ):
            get_recent_messages(hours=1, unread_only=True)
    assert "m.is_read = 0" in mock_query.call_args[0][0]


def test_date_range_replaces_the_hours_window():
    with patch("mac_messages_mcp.messages.query_messages_db") as mock_query:
        mock_query.return_value = []
        with (
            patch(
                "mac_messages_mcp.messages._attachments_for_message_ids",
                return_value={},
            ),
            patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        ):
            get_recent_messages(start_date="2026-01-01", end_date="2026-01-31")
    sql = mock_query.call_args[0][0]
    params = mock_query.call_args[0][1]
    assert "CAST(m.date AS TEXT) >= ?" in sql
    assert "CAST(m.date AS TEXT) < ?" in sql
    assert "CAST(m.date AS TEXT) > ?" not in sql
    start_ns = _to_apple_ns(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert params[0] == str(start_ns)


def test_invalid_dates_are_rejected():
    assert "start_date must be YYYY-MM-DD" in get_recent_messages(
        start_date="01/01/2026",
    )
    assert "end_date must be YYYY-MM-DD" in get_recent_messages(end_date="nope")


def test_cursor_read_ignores_the_hours_window_and_orders_ascending():
    with patch("mac_messages_mcp.messages.query_messages_db") as mock_query:
        mock_query.return_value = []
        with (
            patch(
                "mac_messages_mcp.messages._attachments_for_message_ids",
                return_value={},
            ),
            patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        ):
            result = get_recent_messages(since_rowid=42)
    sql = mock_query.call_args[0][0]
    params = mock_query.call_args[0][1]
    assert "m.ROWID > ?" in sql
    assert "ORDER BY m.date ASC" in sql
    assert "CAST(m.date AS TEXT) >" not in sql
    assert 42 in params
    assert "No new messages since ROWID 42." in result


def test_contact_and_chat_id_are_mutually_exclusive():
    result = get_recent_messages(hours=1, contact="Alice", chat_id="chat1")
    assert "either contact or chat_id" in result


# ---------------------------------------------------------------------------
# Scoped fuzzy search
# ---------------------------------------------------------------------------


def test_fuzzy_search_scoped_by_contact_handle():
    with (
        patch("mac_messages_mcp.messages.query_messages_db", return_value=[]) as query,
        patch(
            "mac_messages_mcp.messages.find_handles_by_phone",
            return_value=[7],
        ),
    ):
        fuzzy_search_messages("x", hours=24, contact="+15551234567")
    sql, params = query.call_args[0]
    assert "m.handle_id IN (?)" in sql
    assert 7 in params
    assert params[0] != 7  # the time cutoff still binds first


def test_fuzzy_search_scoped_by_chat_id():
    with (
        patch("mac_messages_mcp.messages.query_messages_db", return_value=[]) as query,
        patch(
            "mac_messages_mcp.messages._find_chat_by_identifier",
            return_value={"ROWID": 5, "display_name": "Family", "style": 43},
        ),
    ):
        fuzzy_search_messages("x", hours=24, chat_id="chat5")
    sql, params = query.call_args[0]
    assert "chat_message_join" in sql
    assert 5 in params


def test_fuzzy_search_limit_is_validated_and_applied():
    assert "limit must be positive" in fuzzy_search_messages("x", limit=0)

    with patch("mac_messages_mcp.messages.query_messages_db", return_value=[]) as query:
        fuzzy_search_messages("x", hours=24, limit=5)
    # Fetch a multiple of the page, capped by the soft cap.
    assert query.call_args[0][1][-1] == 500


def test_fuzzy_search_rejects_bad_dates():
    assert "start_date must be YYYY-MM-DD" in fuzzy_search_messages(
        "x",
        start_date="bad",
    )


def test_fuzzy_search_truncation_notice():
    rows = [
        _row(ROWID=i, text="needle in haystack", is_from_me=0, handle_id=1)
        for i in range(1, 4)
    ]
    with (
        patch("mac_messages_mcp.messages.query_messages_db", return_value=rows),
        patch(
            "mac_messages_mcp.messages._attachments_for_message_ids", return_value={}
        ),
        patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        patch("mac_messages_mcp.messages.get_contact_name", return_value="Alice"),
    ):
        result = fuzzy_search_messages("needle", hours=24, limit=1)
    assert "Showing the 1 best matches" in result


# ---------------------------------------------------------------------------
# Conversation listing
# ---------------------------------------------------------------------------


def test_list_conversations_labels_kinds_and_unread_counts():
    rows = [
        {
            "chat_row_id": 1,
            "chat_identifier": "iMessage;-;+15550000001",
            "display_name": None,
            "style": 45,
            "message_count": 3,
            "unread_count": 2,
            "last_message_date": _APPLE_NOW,
        },
        {
            "chat_row_id": 2,
            "chat_identifier": "chat999",
            "display_name": "Family",
            "style": 43,
            "message_count": 1,
            "unread_count": 0,
            "last_message_date": None,
        },
    ]
    with patch("mac_messages_mcp.messages.query_messages_db", return_value=rows):
        result = list_conversations()
    assert "[business]" in result
    assert "[group]" in result
    assert "2 unread" in result
    assert "no messages" in result


def test_list_conversations_unread_only_filters_and_can_be_empty():
    rows = [
        {
            "chat_row_id": 1,
            "chat_identifier": "a",
            "display_name": "A",
            "style": None,
            "message_count": 1,
            "unread_count": 0,
            "last_message_date": _APPLE_NOW,
        },
    ]
    with patch("mac_messages_mcp.messages.query_messages_db", return_value=rows):
        assert "unread" in list_conversations(unread_only=True)
        assert "[direct]" in list_conversations()


def test_list_conversations_validates_limit_and_surfaces_db_errors():
    assert "limit must be positive" in list_conversations(limit=0)
    assert "at most 1000" in list_conversations(limit=5000)
    with patch(
        "mac_messages_mcp.messages.query_messages_db",
        return_value=[{"error": "disk error"}],
    ):
        assert "Error accessing chats: disk error" in list_conversations()


# ---------------------------------------------------------------------------
# Waiting for new messages
# ---------------------------------------------------------------------------


def test_wait_returns_immediately_when_a_newer_row_exists():
    with (
        patch(
            "mac_messages_mcp.messages.query_messages_db",
            return_value=[{"max_rowid": 43}],
        ),
        patch(
            "mac_messages_mcp.messages.get_recent_messages",
            return_value="NEW MESSAGES",
        ) as recent,
        patch("mac_messages_mcp.messages.time.sleep") as sleep,
    ):
        result = wait_for_new_messages(since_rowid=42, timeout_seconds=5)
    assert "NEW MESSAGES" in result
    sleep.assert_not_called()
    recent.assert_called_once_with(
        since_rowid=42,
        contact=None,
        chat_id=None,
        limit=50,
    )


def test_wait_times_out_without_new_rows():
    with (
        patch(
            "mac_messages_mcp.messages.query_messages_db",
            return_value=[{"max_rowid": 42}],
        ),
        patch("mac_messages_mcp.messages.time.sleep") as sleep,
        patch(
            "mac_messages_mcp.messages.time.monotonic",
            side_effect=[0.0, 10.0],
        ),
    ):
        result = wait_for_new_messages(since_rowid=42, timeout_seconds=5)
    assert "No new messages arrived within 5 seconds" in result
    assert "cursor ROWID 42" in result
    sleep.assert_not_called()


def test_wait_validates_its_bounds():
    assert "since_rowid cannot be negative" in wait_for_new_messages(since_rowid=-1)
    assert "timeout_seconds must be between" in wait_for_new_messages(
        timeout_seconds=0,
    )
    assert "timeout_seconds must be between" in wait_for_new_messages(
        timeout_seconds=301,
    )
    assert "poll_interval must be positive" in wait_for_new_messages(poll_interval=0)
