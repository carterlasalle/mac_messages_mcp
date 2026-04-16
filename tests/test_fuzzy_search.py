"""
Tests for fuzzy_search_messages — covers time window, message cap, and search quality.

These tests mock query_messages_db and get_chat_mapping so they run without
a real Messages database.  They are written RED-first: the time-window,
message-cap, and search-quality groups should FAIL against the unmodified
upstream code, proving the bugs exist before we fix them.

Test strategy:
- Group A (time window): inspect the function's default parameter and the SQL
  query it generates, since the time filter lives in SQL — not Python.
- Group B (message cap): inspect the SQL query for LIMIT 500.
- Group C (search quality): exercise the Python-side matching via mocked DB
  results, asserting scores are well above the threshold for exact substrings.
- Group D (regressions): existing validation behaviour must be preserved.
- Group E (helpers): unit tests for internal helpers.
"""

import inspect
import itertools
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from mac_messages_mcp.messages import _escape_like, fuzzy_search_messages

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
_ROWID_COUNTER = itertools.count(1)


def _make_message(
    text: str,
    days_ago: float,
    is_from_me: bool = False,
    handle_id: int = 1,
    cache_roomnames: str | None = None,
) -> dict:
    """Build a dict matching the schema returned by query_messages_db."""
    msg_time = datetime.now(timezone.utc) - timedelta(days=days_ago)
    ns_timestamp = int((msg_time - _APPLE_EPOCH).total_seconds() * 1_000_000_000)
    return {
        "ROWID": next(_ROWID_COUNTER),
        "date": ns_timestamp,
        "text": text,
        "attributedBody": None,
        "is_from_me": 1 if is_from_me else 0,
        "handle_id": handle_id,
        "cache_roomnames": cache_roomnames,
    }


def _mock_db_and_call(messages, search_term, **kwargs):
    """Call fuzzy_search_messages with mocked DB, return (result, mock_db)."""
    mock_db = MagicMock(return_value=messages)
    with (
        patch("mac_messages_mcp.messages.query_messages_db", mock_db),
        patch("mac_messages_mcp.messages.get_chat_mapping", return_value={}),
        patch(
            "mac_messages_mcp.messages.get_contact_name",
            return_value="Test Contact",
        ),
    ):
        result = fuzzy_search_messages(search_term, **kwargs)
    return result, mock_db


# ---------------------------------------------------------------------------
# Group A — Time window
# ---------------------------------------------------------------------------


class TestTimeWindow:
    """Default time window should not silently hide older messages."""

    def test_default_hours_at_least_30_days(self):
        """The default hours parameter must be >= 720 (30 days), not 24."""
        sig = inspect.signature(fuzzy_search_messages)
        default_hours = sig.parameters["hours"].default
        assert default_hours >= 720, (
            f"Default hours={default_hours}, expected >= 720 (30 days). "
            f"A 24-hour default causes messages from days ago to be invisible."
        )

    def test_hours_zero_means_no_time_limit(self):
        """hours=0 should search all messages — no timestamp filter in SQL."""
        msgs = [_make_message("Meeting with Eva next week", days_ago=90)]
        result, mock_db = _mock_db_and_call(msgs, "Eva", hours=0)
        # Must not error or return "0 hours" empty message
        assert "Error" not in result
        assert "last 0 hours" not in result
        # The SQL must not contain a timestamp WHERE clause
        query_sql = mock_db.call_args[0][0]
        assert "CAST(m.date AS TEXT) >" not in query_sql, (
            "hours=0 should skip the timestamp filter, but the SQL still "
            "contains a date comparison clause."
        )
        assert "Eva" in result


# ---------------------------------------------------------------------------
# Group B — Message cap
# ---------------------------------------------------------------------------


class TestMessageCap:
    """The function must not silently drop messages beyond an arbitrary cap."""

    def test_no_hard_limit_500_in_sql(self):
        """The SQL query must not contain LIMIT 500 — it silently drops old messages."""
        msgs = [_make_message("Hello from Eva", days_ago=0.5)]
        _result, mock_db = _mock_db_and_call(msgs, "Eva", hours=720)
        query_sql = mock_db.call_args[0][0]
        assert "LIMIT 500" not in query_sql, (
            "SQL still contains LIMIT 500, which silently drops older messages "
            "even when the user requests a large time window."
        )


# ---------------------------------------------------------------------------
# Group C — Search quality
# ---------------------------------------------------------------------------


class TestSearchQuality:
    """Exact and near-exact substring matches must always be found with high scores."""

    def test_exact_substring_scores_above_0_9(self):
        """Short search term 'Eva' in a long message must score > 0.9, not 0.6."""
        long_msg = (
            "I talked to Eva yesterday about the project and she mentioned "
            "several things that were quite interesting to discuss further "
            "with the rest of the team before we make any decisions"
        )
        msgs = [_make_message(long_msg, days_ago=0.5)]
        result, _ = _mock_db_and_call(msgs, "Eva", threshold=0.5)
        assert "No messages found" not in result
        # Parse score from output like "(Score: 0.60)"
        scores = re.findall(r"Score: (\d+\.\d+)", result)
        assert len(scores) >= 1, f"No scores found in result: {result}"
        score = float(scores[0])
        assert score > 0.9, (
            f"Exact substring 'Eva' in message scored {score:.2f}. "
            f"Expected > 0.9 for an exact substring match."
        )

    def test_exact_match_scores_higher_than_fuzzy(self):
        """A message with exact 'divorce' should score higher than one with 'diverse'."""
        msgs = [
            _make_message("We need to discuss the divorce papers", days_ago=0.5),
            _make_message("We have a diverse team of engineers", days_ago=0.5),
        ]
        result, _ = _mock_db_and_call(msgs, "divorce", threshold=0.3)
        lines = result.strip().split("\n")
        # First match line (after header) should be the exact one
        match_lines = [l for l in lines if "Score:" in l]
        assert len(match_lines) >= 1
        assert "divorce papers" in match_lines[0], (
            f"Expected exact match 'divorce papers' to be ranked first, "
            f"but got: {match_lines[0]}"
        )

    def test_short_term_in_very_long_message(self):
        """'Eva' in a 400+ char message must still be found at threshold 0.7."""
        long_msg = "word " * 80 + "Eva" + " word" * 80
        msgs = [_make_message(long_msg, days_ago=0.5)]
        result, _ = _mock_db_and_call(msgs, "Eva", threshold=0.7)
        assert "No messages found" not in result, (
            "Short search term 'Eva' in a very long message was not found "
            "at threshold=0.7. WRatio gives ~60 for short terms in long "
            "messages, which fails at any threshold above 0.6."
        )

    def test_case_insensitive_match(self):
        """Search for 'eva' (lowercase) should find 'EVA'."""
        msgs = [_make_message("Message about EVA project", days_ago=0.5)]
        result, _ = _mock_db_and_call(msgs, "eva", threshold=0.6)
        assert "EVA" in result
        assert "No messages found" not in result


# ---------------------------------------------------------------------------
# Group D — Regressions (should pass on current code already)
# ---------------------------------------------------------------------------


class TestRegressions:
    """Existing validation behaviour must be preserved."""

    def test_empty_search_term_errors(self):
        result = fuzzy_search_messages("")
        assert "Error" in result

    def test_negative_hours_errors(self):
        result = fuzzy_search_messages("test", hours=-1)
        assert "Error" in result

    def test_threshold_validation(self):
        result = fuzzy_search_messages("test", threshold=1.5)
        assert "Error" in result
        result = fuzzy_search_messages("test", threshold=-0.1)
        assert "Error" in result


# ---------------------------------------------------------------------------
# Group E — Helpers
# ---------------------------------------------------------------------------


class TestEscapeLike:
    """_escape_like must neutralise SQL LIKE wildcards."""

    def test_percent_escaped(self):
        assert _escape_like("100%") == "100\\%"

    def test_underscore_escaped(self):
        assert _escape_like("first_name") == "first\\_name"

    def test_backslash_escaped(self):
        assert _escape_like("path\\to") == "path\\\\to"

    def test_plain_text_unchanged(self):
        assert _escape_like("hello world") == "hello world"

    def test_all_special_chars(self):
        assert _escape_like("a%b_c\\d") == "a\\%b\\_c\\\\d"
