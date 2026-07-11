"""
Tests for Apple-epoch timestamp conversion.

These tests pin behaviour around the project's Apple-ns <-> datetime
conversion: the SQL params produced for time-windowed queries, the
date strings rendered for messages, and the seconds-vs-nanoseconds
heuristic for older chat.db rows.

The aim is to give the timestamp logic real coverage so a future
refactor (centralising the inline math into shared helpers) can be
validated as behaviour-preserving rather than relying on it being
written correctly by inspection.
"""

import calendar
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from mac_messages_mcp.messages import (
    _APPLE_EPOCH,
    _to_apple_ns,
    fuzzy_search_messages,
    get_recent_messages,
)

# A specific datetime we'll use across multiple tests. Reference values
# are derived via the Unix epoch and a single 1970->2001 offset so they
# don't share arithmetic with _to_apple_ns -- a multiplier or sign bug
# in the helper would surface, not be cancelled out.
_FIXED_DT = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_APPLE_TO_UNIX_OFFSET_S = 978307200  # seconds between 1970-01-01 and 2001-01-01 UTC
_FIXED_DT_APPLE_S = calendar.timegm(_FIXED_DT.timetuple()) - _APPLE_TO_UNIX_OFFSET_S
_FIXED_DT_APPLE_NS = _FIXED_DT_APPLE_S * 1_000_000_000


class TestToAppleNs(unittest.TestCase):
    """Direct tests for the _to_apple_ns helper."""

    def test_apple_epoch_itself_is_zero(self):
        self.assertEqual(_to_apple_ns(_APPLE_EPOCH), 0)

    def test_one_second_past_epoch(self):
        dt = _APPLE_EPOCH + timedelta(seconds=1)
        self.assertEqual(_to_apple_ns(dt), 1_000_000_000)

    def test_known_datetime_matches_hand_computed_ns(self):
        """If this fails, the multiplier is wrong (1e6 vs 1e9 etc)."""
        self.assertEqual(_to_apple_ns(_FIXED_DT), _FIXED_DT_APPLE_NS)

    def test_naive_datetime_treated_as_utc(self):
        """Behavioural contract: a naive datetime is interpreted as UTC."""
        naive = _FIXED_DT.replace(tzinfo=None)
        self.assertEqual(_to_apple_ns(naive), _FIXED_DT_APPLE_NS)


class TestFromAppleNs(unittest.TestCase):
    """Direct tests for the _from_apple_ns helper.

    This helper does not yet exist on the un-refactored tree -- importing
    it will fail with ImportError. After the centralisation refactor lands,
    these tests should pass and lock in:
      - exact reverse of _to_apple_ns at the epoch and at a known datetime
      - the older-chat.db seconds-format fallback (10-or-fewer digits).
    """

    def setUp(self):
        try:
            from mac_messages_mcp.messages import _from_apple_ns

            self._from_apple_ns = _from_apple_ns
        except ImportError as e:
            self.skipTest(f"_from_apple_ns not yet defined: {e}")

    def test_zero_is_apple_epoch(self):
        self.assertEqual(self._from_apple_ns(0), _APPLE_EPOCH)

    def test_known_apple_ns_round_trip(self):
        self.assertEqual(self._from_apple_ns(_FIXED_DT_APPLE_NS), _FIXED_DT)

    def test_seconds_format_handled(self):
        """Older chat.db rows store seconds (<= 10 digits), not ns."""
        self.assertEqual(self._from_apple_ns(_FIXED_DT_APPLE_S), _FIXED_DT)

    def test_round_trip_preserves_datetime(self):
        ns = _to_apple_ns(_FIXED_DT)
        self.assertEqual(self._from_apple_ns(ns), _FIXED_DT)


class TestGetRecentMessagesDateFormatting(unittest.TestCase):
    """Pin observable date formatting on get_recent_messages.

    A message row with a known Apple-ns date should render with the
    matching date string. Catches direction-swap and unit errors that
    pure-helper unit tests might miss in integration.
    """

    @patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
    @patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Alice")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_known_apple_ns_renders_expected_year(self, mock_query, *_):
        mock_query.return_value = [
            {
                "ROWID": 100,
                "date": _FIXED_DT_APPLE_NS,
                "text": "hello",
                "attributedBody": None,
                "is_from_me": 0,
                "handle_id": 1,
                "cache_roomnames": None,
            }
        ]
        result = get_recent_messages(hours=24)
        # The exact local time depends on the machine's tz, but the UTC
        # date is fixed -- so the year and month should appear.
        self.assertIn("2024-01-1", result)  # tolerant of TZ shifting day

    @patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
    @patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
    @patch("mac_messages_mcp.messages.get_contact_name", return_value="Alice")
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_seconds_format_row_renders_expected_year(self, mock_query, *_):
        """Older chat.db rows store seconds-since-2001 (<= 10 digits)."""
        mock_query.return_value = [
            {
                "ROWID": 100,
                "date": _FIXED_DT_APPLE_S,
                "text": "hello",
                "attributedBody": None,
                "is_from_me": 0,
                "handle_id": 1,
                "cache_roomnames": None,
            }
        ]
        result = get_recent_messages(hours=24)
        self.assertIn("2024-01-1", result)


class TestFuzzySearchTimestampParam(unittest.TestCase):
    """Pin the SQL param value generated for fuzzy_search_messages's
    time window. Catches multiplier and direction errors that wouldn't
    surface in tests asserting only SQL structure.
    """

    @patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
    @patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_window_param_is_apple_ns_within_tolerance(self, mock_query, *_):
        """The first param (the time-window cutoff) should be an
        Apple-ns string that decodes to roughly (now - hours)."""
        mock_query.return_value = []
        before = datetime.now(timezone.utc)
        fuzzy_search_messages(search_term="x", hours=24, threshold=0.5)
        after = datetime.now(timezone.utc)

        # First call's first positional arg = sql, second = params tuple
        sql, params = mock_query.call_args[0]
        # Time-window cutoff is the first param (insert(0, ...) in source)
        cutoff_str = params[0]
        self.assertIsInstance(cutoff_str, str)
        cutoff_ns = int(cutoff_str)

        expected_low = _to_apple_ns(before - timedelta(hours=24))
        expected_high = _to_apple_ns(after - timedelta(hours=24))
        # Allow up to 1 second of slop for the now() drift between
        # before/after measurements.
        self.assertGreaterEqual(
            cutoff_ns, expected_low - 10**9, f"cutoff {cutoff_ns} too small"
        )
        self.assertLessEqual(
            cutoff_ns, expected_high + 10**9, f"cutoff {cutoff_ns} too large"
        )

    @patch("mac_messages_mcp.messages._attachments_for_message_ids", return_value={})
    @patch("mac_messages_mcp.messages.get_chat_mapping", return_value={})
    @patch("mac_messages_mcp.messages.query_messages_db")
    def test_zero_hours_omits_time_window(self, mock_query, *_):
        """The hours=0 ('all time') branch must not emit a time cutoff."""
        mock_query.return_value = []
        fuzzy_search_messages(search_term="x", hours=0, threshold=0.5)
        sql, params = mock_query.call_args[0]
        # When hours=0, no time cutoff is inserted -- so the LIKE param is
        # the first positional. There should be no Apple-ns-shaped string.
        self.assertNotIn("CAST(m.date AS TEXT) >", sql)


if __name__ == "__main__":
    unittest.main()
