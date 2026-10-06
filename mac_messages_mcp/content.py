# Copyright (c) 2023 Carter Lasalle
"""Attachment *content* search for the Messages database.

``messages.search_attachments`` only matches attachment metadata (filename,
MIME type, dates). This module adds a best-effort full-text scan of the
attachment files themselves: plain text is read directly, PDFs are text
extracted with ``pypdf`` when installed, and images are OCR'd with
``pytesseract``/``tesseract`` when available.

Every step degrades gracefully: unreadable files are counted, unsupported
types are counted, and missing optional dependencies never raise. Output is
fenced through the untrusted-output boundary, like the rest of the suite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import messages
from .untrusted import bound_untrusted_output, neutralize_untrusted_text

# Plain-text-ish extensions we decode directly even when chat.db has no MIME
# type (or a generic one) for the attachment.
_TEXT_EXTENSIONS = {
    "txt",
    "md",
    "csv",
    "tsv",
    "json",
    "log",
    "xml",
    "html",
    "htm",
    "yaml",
    "yml",
    "srt",
    "vtt",
}

# Longest snippet returned for a match, in characters.
_MAX_SNIPPET_CHARS = 200

# PDFs can be huge; only the first pages carry the human-readable content.
_MAX_PDF_PAGES = 50


def _validate_dates(
    start_date: str | None,
    end_date: str | None,
) -> tuple[str | None, list[str], list[Any]]:
    """Validate ISO dates and build the ``WHERE`` fragments and params.

    Returns ``(error, where_clauses, params)``. ``error`` is non-None only
    when a supplied date is not a ``YYYY-MM-DD`` string.
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if start_date:
        try:
            dt = datetime.strptime(start_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            return (
                f"Error: start_date must be YYYY-MM-DD, got '{start_date}'.",
                [],
                [],
            )
        where_clauses.append("CAST(m.date AS INTEGER) >= ?")
        params.append(messages._to_apple_ns(dt))

    if end_date:
        try:
            dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            return (
                f"Error: end_date must be YYYY-MM-DD, got '{end_date}'.",
                [],
                [],
            )
        # Inclusive: the exclusive bound is the start of the following day.
        dt_end = dt + timedelta(days=1)
        where_clauses.append("CAST(m.date AS INTEGER) < ?")
        params.append(messages._to_apple_ns(dt_end))

    return None, where_clauses, params


def _resolve_contact_handles(contact: str) -> list[int] | None:
    """Resolve a contact selector to handle ROWIDs, or None when unknown.

    Mirrors ``messages.search_attachments``: email handles are looked up
    case-insensitively, digit-containing inputs go through the phone resolver,
    and anything else is treated as a name and fuzzy matched.
    """
    contact = str(contact).strip()
    if "@" in contact:
        results = messages.query_messages_db(
            "SELECT ROWID FROM handle WHERE id = ? COLLATE NOCASE",
            (messages.canonical_handle(contact) or contact.strip(),),
        )
        if results and "error" not in results[0]:
            return [r["ROWID"] for r in results]
        return None
    if any(c.isdigit() for c in contact):
        return messages.find_handles_by_phone(contact)
    matches = messages.find_contact_by_name(contact)
    if not matches:
        return None
    resolved: list[int] = []
    for match in matches:
        handles = messages.find_handles_by_phone(match["phone"]) or []
        resolved.extend(handles)
    return resolved or None


def _build_search_query(
    start_date: str | None,
    end_date: str | None,
    contact: str | None,
    mime_type: str | None,
    fetch_limit: int,
) -> tuple[str | None, tuple[Any, ...], str | None]:
    """Build the attachment-join query shared with ``search_attachments``.

    Returns ``(error, params, query)``. ``error`` is non-None for a bad date
    or an unresolvable contact.
    """
    date_error, where_clauses, params = _validate_dates(start_date, end_date)
    if date_error is not None:
        return date_error, (), None

    if mime_type:
        like_pattern = mime_type if "%" in mime_type else f"{mime_type}%"
        where_clauses.append("a.mime_type LIKE ?")
        params.append(like_pattern)

    if contact:
        handle_ids = _resolve_contact_handles(contact)
        if not handle_ids:
            return f"No handles found for contact '{contact}'.", (), None
        placeholders = ",".join(["?"] * len(handle_ids))
        where_clauses.append(f"m.handle_id IN ({placeholders})")
        params.extend(handle_ids)

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
        SELECT
            {messages._ATTACHMENT_SELECT_COLS},
            m.date AS message_date,
            m.is_from_me AS is_from_me,
            m.handle_id AS handle_id
        FROM message_attachment_join maj
        JOIN attachment a ON a.ROWID = maj.attachment_id
        JOIN message m ON m.ROWID = maj.message_id
        {where_sql}
        ORDER BY m.date DESC
        LIMIT ?
    """
    return None, (*params, fetch_limit), query


def _read_text_file(path: str, max_file_bytes: int) -> tuple[str | None, str | None]:
    """Read a text-like file, returning ``(text, skip_reason)``."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(max_file_bytes)
    except OSError:
        return None, "unreadable"
    return raw.decode("utf-8", errors="replace"), None


def _read_pdf_file(path: str) -> tuple[str | None, str | None]:
    """Extract text from the first pages of a PDF, or explain the skip."""
    try:
        import pypdf  # type: ignore[import-untyped]
    except ImportError:
        return None, "pdf_unsupported"

    try:
        reader = pypdf.PdfReader(path)
        pages = reader.pages[:_MAX_PDF_PAGES]
        texts = [page.extract_text() or "" for page in pages]
    except OSError:
        return None, "unreadable"
    except Exception:
        # Malformed/encrypted PDFs must not abort the whole search.
        return None, "unreadable"
    return "\n".join(texts), None


def _read_image_file(path: str) -> tuple[str | None, str | None]:
    """OCR an image when tesseract is available, or explain the skip."""
    try:
        import pytesseract  # type: ignore[import-untyped]

        pytesseract.get_tesseract_version()
    except Exception:
        return None, "ocr_unsupported"

    try:
        from PIL import Image

        with Image.open(path) as image:
            text = pytesseract.image_to_string(image)
    except OSError:
        return None, "unreadable"
    except Exception:
        return None, "unreadable"
    return text, None


def _extract_attachment_text(
    path: str,
    mime_type: str | None,
    max_file_bytes: int,
) -> tuple[str | None, str | None]:
    """Extract searchable text from one attachment file.

    Returns ``(text, skip_reason)``. ``text`` is None when the row could not
    be extracted; ``skip_reason`` is one of ``unreadable``,
    ``pdf_unsupported``, ``ocr_unsupported`` or ``unsupported_type``.
    """
    mime = (mime_type or "").lower()
    suffix = Path(path).suffix.lstrip(".").lower()

    if mime.startswith("text/") or suffix in _TEXT_EXTENSIONS:
        return _read_text_file(path, max_file_bytes)
    if mime == "application/pdf":
        return _read_pdf_file(path)
    if mime.startswith("image/"):
        return _read_image_file(path)
    return None, "unsupported_type"


def _make_snippet(text: str, query: str) -> str:
    """Return at most ``_MAX_SNIPPET_CHARS`` centred on the first match.

    Leading/trailing ``...`` are added when the window is clipped from the
    surrounding text. Returns an empty string when the query is absent.
    """
    lowered = text.lower()
    needle = query.lower()
    index = lowered.find(needle)
    if index < 0:
        return ""

    window = _MAX_SNIPPET_CHARS
    lead = max(0, (window - len(needle)) // 2)
    start = max(0, index - lead)
    end = min(len(text), start + window)
    start = max(0, end - window)

    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _format_match_line(
    shaped: dict[str, Any],
    row: dict[str, Any],
    snippet: str,
) -> str:
    """Format one content match as the public single-line result."""
    filename = shaped.get("filename")
    if not filename and shaped.get("path"):
        filename = Path(shaped["path"]).name
    filename = neutralize_untrusted_text(filename or "(no name)")
    mime = neutralize_untrusted_text(shaped.get("mime_type") or "unknown")

    try:
        date_str = (
            messages._from_apple_ns(int(row["message_date"]))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except (KeyError, ValueError, TypeError, OverflowError):
        date_str = "Unknown date"

    return (
        f"#{shaped['id']} {filename} [{mime}] "
        f"(message #{shaped['message_id']}, {date_str}) - {snippet}"
    )


def _format_skip_line(skipped: dict[str, int]) -> str | None:
    """Render the non-zero skip counts, or None when nothing was skipped."""
    parts: list[str] = []
    if skipped["missing"]:
        parts.append(f"{skipped['missing']} missing file(s)")
    if skipped["pdf_unsupported"]:
        parts.append(f"{skipped['pdf_unsupported']} pdf (pypdf not installed)")
    if skipped["ocr_unsupported"]:
        parts.append(f"{skipped['ocr_unsupported']} image (pytesseract not installed)")
    if skipped["unsupported_type"]:
        parts.append(f"{skipped['unsupported_type']} unsupported type(s)")
    if skipped["unreadable"]:
        parts.append(f"{skipped['unreadable']} unreadable file(s)")
    if not parts:
        return None

    line = "Skipped: " + ", ".join(parts) + "."
    hints: list[str] = []
    if skipped["pdf_unsupported"]:
        hints.append("Install PDF text support with: pip install pypdf.")
    if skipped["ocr_unsupported"]:
        hints.append(
            "Install OCR support with: pip install pytesseract and "
            "the tesseract binary.",
        )
    if hints:
        line += " " + " ".join(hints)
    return line


@bound_untrusted_output
def search_attachment_contents(
    query: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    contact: str | None = None,
    mime_type: str | None = None,
    limit: int = 20,
    max_file_bytes: int = 2_000_000,
) -> str:
    """Search attachment *contents* (not just metadata) for a substring.

    Text-like files are read directly, PDFs are text extracted with ``pypdf``
    when installed, and images are OCR'd when ``pytesseract`` and the
    tesseract binary are available. Missing files and unsupported types are
    counted and reported but never abort the search.

    Args:
        query: Case-insensitive substring to look for.
        start_date: Inclusive ISO date "YYYY-MM-DD" (UTC). Optional.
        end_date: Inclusive ISO date "YYYY-MM-DD" (UTC). Optional.
        contact: Phone number, email, or contact name. Optional.
        mime_type: Prefix match e.g. "image/" or "application/pdf". Optional.
        limit: Maximum number of matching attachments to return.
        max_file_bytes: Byte cap when reading text-like files.

    """
    if not query or not query.strip():
        return "Error: query cannot be empty."
    if limit <= 0:
        return "Error: limit must be positive."

    # Pull extra rows so filtering (stickers, plugin payloads, misses) can
    # still leave us with `limit` matches.
    fetch_limit = limit * 5
    error, params, sql = _build_search_query(
        start_date,
        end_date,
        contact,
        mime_type,
        fetch_limit,
    )
    if error is not None:
        return error

    rows = messages.query_messages_db(sql, params)  # type: ignore[arg-type]
    if rows and "error" in rows[0]:
        return f"Error querying attachments: {rows[0]['error']}"

    rows = messages._filter_excluded_attachments(rows)

    safe_query = neutralize_untrusted_text(query)
    matches: list[str] = []
    skipped = {
        "missing": 0,
        "pdf_unsupported": 0,
        "ocr_unsupported": 0,
        "unsupported_type": 0,
        "unreadable": 0,
    }
    scanned = 0

    for row in rows:
        if len(matches) >= limit:
            break
        scanned += 1
        shaped = messages._shape_attachment(row)
        path = shaped.get("path")
        if not path or not shaped.get("exists"):
            skipped["missing"] += 1
            continue

        text, reason = _extract_attachment_text(
            path,
            shaped.get("mime_type"),
            max_file_bytes,
        )
        if reason is not None:
            skipped[reason] += 1
            continue
        if not text or query.lower() not in text.lower():
            continue

        snippet = _make_snippet(text, query)
        matches.append(_format_match_line(shaped, row, snippet))

    lines: list[str] = []
    if matches:
        lines.append(f"Found {len(matches)} attachment(s) containing '{safe_query}':")
        lines.extend(matches)
    else:
        lines.append(
            f"No attachment contents matched '{safe_query}' in "
            f"{scanned} scanned attachment(s).",
        )

    skip_line = _format_skip_line(skipped)
    if skip_line is not None:
        lines.append(skip_line)

    lines.extend(
        (
            "",
            "Use tool_get_attachment(attachment_id=<id>) to fetch a specific file.",
        ),
    )
    return "\n".join(lines)
