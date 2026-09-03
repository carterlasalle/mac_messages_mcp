"""
Core functionality for interacting with macOS Messages app
"""

import difflib
import glob
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import Image
from thefuzz import fuzz

from .phone import (
    canonical_handle,
    contact_key,
    digits_only,
    get_default_region,
    handle_variants,
    is_email_handle,
    lookup_keys,
    to_dialable_e164,
)
from .untrusted import bound_untrusted_output, neutralize_untrusted_text

_APPLESCRIPT_TIMEOUT_SECONDS = 30


def _connect_sqlite_readonly(path: str) -> sqlite3.Connection:
    """Open a local SQLite database without write, journal, or creation access."""
    uri = f"{Path(path).expanduser().resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def run_applescript(script: str, timeout: float = _APPLESCRIPT_TIMEOUT_SECONDS) -> str:
    """Run an AppleScript and return the result."""
    proc = subprocess.Popen(
        ["osascript", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return f"Error: AppleScript timed out after {timeout:g} seconds"
    if proc.returncode != 0:
        return f"Error: {err.decode('utf-8')}"
    return out.decode("utf-8").strip()


def escape_applescript(value: str) -> str:
    """Escape a string for safe interpolation into an AppleScript double-quoted string.

    Escapes backslashes first (so subsequent escapes aren't double-escaped), then
    double quotes, then control characters that would otherwise terminate the
    AppleScript string literal or break the script (newlines, carriage returns,
    tabs). Also handles Unicode line/paragraph separators (U+2028 / U+2029),
    which AppleScript treats as line terminators.
    """
    if value is None:
        return ""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\u2028", "\\n")
        .replace("\u2029", "\\n")
    )


def get_chat_mapping() -> Dict[str, str]:
    """
    Get mapping from room_name to display_name in chat table.

    Returns an empty dict if the database is inaccessible or locked.
    """
    conn = None
    try:
        conn = _connect_sqlite_readonly(get_messages_db_path())
        cursor = conn.cursor()
        cursor.execute("SELECT room_name, display_name FROM chat")
        result_set = cursor.fetchall()
        return {room_name: display_name for room_name, display_name in result_set}
    except Exception as e:
        print(f"Error reading chat mapping: {e}")
        return {}
    finally:
        if conn:
            conn.close()


def extract_body_from_attributed(attributed_body):
    """
    Extract message content from attributedBody binary data.

    The attributedBody column contains an Apple typedstream blob
    (NSArchiver serialization of NSMutableAttributedString).  The string
    content is stored after the first ``NSString`` class marker followed
    by a 5-byte header (``\\x01 <byte> \\x84 \\x01 +``) and a
    variable-length integer encoding the byte length of the UTF-8 text.

    Length encoding (first byte after the header):
        < 0x80  — the byte *is* the length.
        0x81    — next 2 bytes (little-endian) are the length.
        0x82    — next 3 bytes (little-endian) are the length.
        0x83    — next 4 bytes (little-endian) are the length.
    """
    if attributed_body is None:
        return None

    try:
        # Locate the first NSString class reference in the blob.
        marker = b"NSString"
        idx = attributed_body.find(marker)
        if idx < 0:
            return None

        # Skip past: NSString (8) + \x01 + <byte> + \x84 + \x01 + '+' = 5 bytes
        pos = idx + len(marker) + 5

        if pos >= len(attributed_body):
            return None

        # Read the variable-length integer for the text byte count.
        length_byte = attributed_body[pos]
        pos += 1

        if length_byte < 0x80:
            text_length = length_byte
        elif length_byte == 0x81:
            if pos + 2 > len(attributed_body):
                return None
            text_length = attributed_body[pos] | (attributed_body[pos + 1] << 8)
            pos += 2
        elif length_byte == 0x82:
            if pos + 3 > len(attributed_body):
                return None
            text_length = (
                attributed_body[pos]
                | (attributed_body[pos + 1] << 8)
                | (attributed_body[pos + 2] << 16)
            )
            pos += 3
        elif length_byte == 0x83:
            if pos + 4 > len(attributed_body):
                return None
            text_length = (
                attributed_body[pos]
                | (attributed_body[pos + 1] << 8)
                | (attributed_body[pos + 2] << 16)
                | (attributed_body[pos + 3] << 24)
            )
            pos += 4
        else:
            return None

        if pos + text_length > len(attributed_body):
            return None

        return attributed_body[pos : pos + text_length].decode(
            "utf-8", errors="replace"
        )

    except Exception:
        return None


def get_messages_db_path() -> str:
    """Get the path to the Messages database."""
    home_dir = os.path.expanduser("~")
    return os.path.join(home_dir, "Library/Messages/chat.db")


def query_messages_db(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Query the Messages database and return results as a list of dictionaries."""
    try:
        db_path = get_messages_db_path()

        # Check if the database file exists and is accessible
        if not os.path.exists(db_path):
            return [{"error": f"Messages database not found at {db_path}"}]

        # Try to connect to the database
        try:
            conn = _connect_sqlite_readonly(db_path)
        except sqlite3.OperationalError as e:
            return [
                {
                    "error": f"Cannot access Messages database. Please grant Full Disk Access permission to your terminal application in System Preferences > Security & Privacy > Privacy > Full Disk Access. Error: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
                }
            ]

        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    except Exception as e:
        return [{"error": str(e)}]


def normalize_phone_number(phone: str) -> str:
    """
    Normalize a phone number by removing all non-digit characters.
    """
    return digits_only(phone)


def _format_phone_for_messages(phone: str) -> str:
    """
    Return the phone number format Messages resolves most reliably.

    National-format numbers are expanded using the region this Mac is
    configured for, so ``06 39 98 00 01`` becomes ``+33639980001`` in France
    and ``(555) 555-0142`` becomes ``+15555550142`` in the United States.
    Returns an empty string when the input is not a usable phone number.

    Numbers that are only dialable from inside their own local area, a
    seven-digit NANP local among them, are refused rather than expanded, so a
    half-typed number is reported back to the caller instead of being handed
    to Messages.app. That test comes from the numbering plan, not from a digit
    count, which is why an eight-digit Norwegian number is accepted.
    """
    return to_dialable_e164(phone) or ""


def _looks_like_phone_input(value: str) -> bool:
    """
    True when the input is intended as a phone number, not a contact name.

    Accepts the separators people actually type, including the dots used in
    French national notation (``05.39.98.00.03``).
    """
    return bool(value) and all(c.isdigit() or c in "+-. ()" for c in value)


# Global cache for contacts map
_CONTACTS_CACHE = None
_LAST_CACHE_UPDATE = 0
_CACHE_TTL = 300  # 5 minutes in seconds

# Inclusive (start, end) code-point ranges for characters stripped as emoji.
# Kept as ordinal comparisons so CodeQL py/overly-large-range does not treat
# supplementary-plane regex ranges as overlapping U+FFFD, and so the old
# catch-all U+24C2–U+1F251 span cannot swallow CJK and other non-emoji text.
_EMOJI_ORDINAL_RANGES = (
    (0x1F600, 0x1F64F),  # emoticons
    (0x1F300, 0x1F5FF),  # symbols & pictographs
    (0x1F680, 0x1F6FF),  # transport & map symbols
    (0x1F700, 0x1F77F),  # alchemical symbols
    (0x1F780, 0x1F7FF),  # geometric shapes extended
    (0x1F800, 0x1F8FF),  # supplemental arrows-C
    (0x1F900, 0x1F9FF),  # supplemental symbols and pictographs
    (0x1FA00, 0x1FA6F),  # chess symbols
    (0x1FA70, 0x1FAFF),  # symbols and pictographs extended-A
    (0x2702, 0x27B0),  # dingbats
    (0x2600, 0x26FF),  # miscellaneous symbols (☀, ⚡, ♥, …)
    (0x24C2, 0x24C2),  # circled M
    (0x1F170, 0x1F251),  # enclosed alphanumeric supplement through 🉑
)


def _is_emoji_codepoint(codepoint: int) -> bool:
    return any(start <= codepoint <= end for start, end in _EMOJI_ORDINAL_RANGES)


def _strip_emoji(text: str) -> str:
    return "".join(ch for ch in text if not _is_emoji_codepoint(ord(ch)))


_MAX_MESSAGE_BODY_CHARS = 4_000


def _clean_text(text: str, strip_punctuation: bool = False) -> str:
    """Remove emoji and normalise whitespace.

    Args:
        text: The string to clean.
        strip_punctuation: If True, also remove all characters that are not
            alphanumeric, whitespace, apostrophes, or hyphens (used for
            contact-name matching).
    """
    text = _strip_emoji(text)
    if strip_punctuation:
        text = re.sub(r"[^\w\s\'\-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sanitize_message_body(text: str, max_chars: int = _MAX_MESSAGE_BODY_CHARS) -> str:
    """Defense-in-depth field sanitizer for message bodies.

    The MCP security boundary is ``present_untrusted_output`` /
    ``bound_untrusted_output``. This helper still serializes a single body so
    a missed interpolation is less likely to introduce a structural line.
    """
    return neutralize_untrusted_text(text, max_chars=max_chars)


def clean_name(name: str) -> str:
    """
    Clean a name by removing emojis, punctuation, and extra whitespace.
    """
    return _clean_text(name, strip_punctuation=True)


def fuzzy_match(
    query: str, candidates: List[Tuple[str, Any]], threshold: float = 0.6
) -> List[Tuple[str, Any, float]]:
    """
    Find fuzzy matches between query and a list of candidates using token-based matching.

    Uses token-based matching to properly handle first name searches:
    - Exact token match (e.g., "alex" matches first name "Alex") scores 0.95
    - Query as prefix of token scores 0.85
    - Token as prefix of query scores 0.80
    - Fuzzy match on individual tokens uses best token score

    Args:
        query: The search string
        candidates: List of (name, value) tuples to search through
        threshold: Minimum similarity score (0-1) to consider a match

    Returns:
        List of (name, value, score) tuples for matches, sorted by score
    """
    query = clean_name(query).lower()
    if not query:
        return []

    results = []

    for name, value in candidates:
        clean_candidate = clean_name(name).lower()

        # Try exact full match first (case insensitive)
        if query == clean_candidate:
            results.append((name, value, 1.0))
            continue

        # Token-based matching: split candidate into words/tokens
        tokens = clean_candidate.split()
        best_token_score = 0.0

        for token in tokens:
            # Exact token match (e.g., query "alex" matches token "alex")
            if query == token:
                best_token_score = max(best_token_score, 0.95)
            # Query is prefix of token (e.g., "ale" matches "alex")
            elif token.startswith(query):
                # Score based on how much of the token is matched
                prefix_score = 0.85 * (len(query) / len(token))
                best_token_score = max(best_token_score, prefix_score)
            # Token is prefix of query (e.g., "alex" when searching "alexis")
            elif query.startswith(token):
                prefix_score = 0.80 * (len(token) / len(query))
                best_token_score = max(best_token_score, prefix_score)
            else:
                # Fuzzy match on individual token
                token_score = difflib.SequenceMatcher(None, query, token).ratio()
                best_token_score = max(best_token_score, token_score)

        # Also try matching query against full name for multi-word queries
        if " " in query or best_token_score < threshold:
            full_score = difflib.SequenceMatcher(None, query, clean_candidate).ratio()
            best_token_score = max(best_token_score, full_score)

        if best_token_score >= threshold:
            results.append((name, value, best_token_score))

    # Sort results by score (highest first)
    return sorted(results, key=lambda x: x[2], reverse=True)


def query_addressbook_db(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Query the AddressBook database and return results as a list of dictionaries."""
    try:
        # Find the AddressBook database paths
        home_dir = os.path.expanduser("~")
        # Check both the top-level DB and source-specific DBs (iCloud, Google, Exchange, etc.)
        toplevel_path = os.path.join(
            home_dir, "Library/Application Support/AddressBook/AddressBook-v22.abcddb"
        )
        sources_path = os.path.join(
            home_dir,
            "Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb",
        )
        db_paths = glob.glob(sources_path)
        if os.path.exists(toplevel_path):
            db_paths.append(toplevel_path)

        if not db_paths:
            return [
                {
                    "error": f"AddressBook database not found at {sources_path} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
                }
            ]

        # Try each database path until one works
        all_results = []
        for db_path in db_paths:
            try:
                conn = _connect_sqlite_readonly(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, params)
                results = [dict(row) for row in cursor.fetchall()]
                conn.close()
                all_results.extend(results)
            except sqlite3.OperationalError as e:
                # If we can't access this one, try the next database
                print(f"Warning: Cannot access {db_path}: {str(e)}")
                continue

        if not all_results and len(db_paths) > 0:
            return [
                {
                    "error": f"Could not access any AddressBook databases. Please grant Full Disk Access permission. PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
                }
            ]

        return all_results
    except Exception as e:
        return [{"error": str(e)}]


def get_addressbook_contacts() -> Dict[str, str]:
    """
    Query the macOS AddressBook database to get contacts and their phone numbers.
    Returns a dictionary mapping normalized phone numbers to contact names.
    """
    contacts_map = {}

    # Define the query to get contact names, nicknames, and phone numbers
    phone_query = """
    SELECT
        ZABCDRECORD.ZFIRSTNAME as first_name,
        ZABCDRECORD.ZLASTNAME as last_name,
        ZABCDRECORD.ZNICKNAME as nickname,
        ZABCDPHONENUMBER.ZFULLNUMBER as phone
    FROM
        ZABCDRECORD
        LEFT JOIN ZABCDPHONENUMBER ON ZABCDRECORD.Z_PK = ZABCDPHONENUMBER.ZOWNER
    WHERE
        ZABCDPHONENUMBER.ZFULLNUMBER IS NOT NULL
    ORDER BY
        ZABCDRECORD.ZLASTNAME,
        ZABCDRECORD.ZFIRSTNAME,
        ZABCDPHONENUMBER.ZORDERINGINDEX ASC
    """

    # Query for email-based contacts (used by iMessage when handle is an email)
    email_query = """
    SELECT
        ZABCDRECORD.ZFIRSTNAME as first_name,
        ZABCDRECORD.ZLASTNAME as last_name,
        ZABCDRECORD.ZNICKNAME as nickname,
        ZABCDEMAILADDRESS.ZADDRESS as email
    FROM
        ZABCDRECORD
        LEFT JOIN ZABCDEMAILADDRESS ON ZABCDRECORD.Z_PK = ZABCDEMAILADDRESS.ZOWNER
    WHERE
        ZABCDEMAILADDRESS.ZADDRESS IS NOT NULL
    ORDER BY
        ZABCDRECORD.ZLASTNAME,
        ZABCDRECORD.ZFIRSTNAME
    """

    try:
        # For testing/fallback, parse the user-provided examples in cases where direct DB access fails
        # This is a temporary workaround until full disk access is granted
        if (
            "USE_TEST_DATA" in os.environ
            and os.environ["USE_TEST_DATA"].lower() == "true"
        ):
            contacts = [
                {"first_name": "TEST", "last_name": "TEST", "phone": "+11111111111"}
            ]
            return process_contacts(contacts)

        # Try to query database directly
        results = query_addressbook_db(phone_query)

        if results and "error" in results[0]:
            print(f"Error getting AddressBook contacts: {results[0]['error']}")
            return {}

        # Also query email addresses for email-based iMessage handles
        email_results = query_addressbook_db(email_query)
        if email_results and not (
            len(email_results) > 0 and "error" in email_results[0]
        ):
            results.extend(email_results)

        return process_contacts(results)
    except Exception as e:
        print(f"Error getting AddressBook contacts: {str(e)}")
        return {}


def process_contacts(contacts) -> Dict[str, str]:
    """Process contact records into a normalized phone -> name map"""
    contacts_map = {}
    name_to_numbers = {}  # For reverse lookup
    phone_to_details = {}  # Store first_name, last_name, nickname for fuzzy matching

    for contact in contacts:
        try:
            first_name = contact.get("first_name", "") or ""
            last_name = contact.get("last_name", "") or ""
            nickname = contact.get("nickname", "") or ""
            phone = contact.get("phone", "")
            email = contact.get("email", "")

            # Create full name
            full_name = " ".join(filter(None, [first_name, last_name]))
            if not full_name.strip():
                continue

            # Handle email-based contacts (iMessage handles can be email addresses)
            if email and not phone:
                email_lower = email.strip().lower()
                contacts_map[email_lower] = full_name

                phone_to_details[email_lower] = {
                    "first_name": first_name.strip(),
                    "last_name": last_name.strip(),
                    "nickname": nickname.strip(),
                    "full_name": full_name,
                }

                if full_name not in name_to_numbers:
                    name_to_numbers[full_name] = []
                name_to_numbers[full_name].append(email_lower)
                continue

            # Skip entries without phone numbers
            if not phone:
                continue

            # Clean up phone number and remove any image metadata
            if "X-IMAGETYPE" in phone:
                phone = phone.split("X-IMAGETYPE")[0]

            # Key the map on the canonical (E.164) form so a number stored as
            # "06 39 98 00 01" in the address book matches the "+33639980001"
            # handle the Messages database recorded for the same person.
            # Short codes and entries the parser cannot read keep a digits-only
            # key rather than being dropped from the map entirely.
            normalized_phone = contact_key(phone)
            if normalized_phone:
                contacts_map[normalized_phone] = full_name

                # Store detailed info for fuzzy matching
                phone_to_details[normalized_phone] = {
                    "first_name": first_name.strip(),
                    "last_name": last_name.strip(),
                    "nickname": nickname.strip(),
                    "full_name": full_name,
                }

                # Add to reverse lookup
                if full_name not in name_to_numbers:
                    name_to_numbers[full_name] = []
                name_to_numbers[full_name].append(normalized_phone)
        except Exception as e:
            # Skip individual entries that fail to process
            print(f"Error processing contact: {str(e)}")
            continue

    # Store the reverse lookup in a global variable for later use
    global _NAME_TO_NUMBERS_MAP, _PHONE_TO_DETAILS_MAP
    _NAME_TO_NUMBERS_MAP = name_to_numbers
    _PHONE_TO_DETAILS_MAP = phone_to_details

    return contacts_map


# Global variables for contact lookup
_NAME_TO_NUMBERS_MAP = {}
_PHONE_TO_DETAILS_MAP = {}  # phone -> {first_name, last_name, nickname, full_name}


def get_cached_contacts() -> Dict[str, str]:
    """Get cached contacts map or refresh if needed"""
    global _CONTACTS_CACHE, _LAST_CACHE_UPDATE

    current_time = time.time()
    if _CONTACTS_CACHE is None or (current_time - _LAST_CACHE_UPDATE) > _CACHE_TTL:
        _CONTACTS_CACHE = get_addressbook_contacts()
        _LAST_CACHE_UPDATE = current_time

    return _CONTACTS_CACHE


def find_contact_by_name(name: str) -> List[Dict[str, Any]]:
    """
    Find contacts by name or nickname using fuzzy matching.

    Searches against:
    - Full name (first + last)
    - Nickname

    Args:
        name: The name or nickname to search for

    Returns:
        List of matching contacts (may be multiple if ambiguous)
    """
    contacts = get_cached_contacts()
    global _PHONE_TO_DETAILS_MAP

    # Build candidates: search both full name and nickname
    candidates = []
    for phone, contact_name in contacts.items():
        # Add full name as searchable
        candidates.append((contact_name, phone))

        # Add nickname as searchable (if exists)
        details = _PHONE_TO_DETAILS_MAP.get(phone, {})
        nickname = details.get("nickname", "")
        if nickname:
            candidates.append((nickname, phone))

    # Perform fuzzy matching
    matches = fuzzy_match(name, candidates)

    # Deduplicate by phone number, keeping highest score for each
    seen_phones = {}
    for matched_name, phone, score in matches:
        if phone not in seen_phones or score > seen_phones[phone]["score"]:
            # Get the display name (full name, not nickname)
            display_name = contacts.get(phone, matched_name)
            display_phone = (
                phone if "@" in phone else (_format_phone_for_messages(phone) or phone)
            )
            seen_phones[phone] = {
                "name": display_name,
                "phone": display_phone,
                "score": score,
                "matched_on": matched_name,  # What actually matched (name or nickname)
            }

    # Convert to sorted list
    results = sorted(seen_phones.values(), key=lambda x: x["score"], reverse=True)
    return results


def send_message(recipient: str, message: str, group_chat: bool = False) -> str:
    """
    Send a message using the Messages app with improved contact resolution.

    Args:
        recipient: Phone number, email, contact name, or special format for contact selection
                  Use "contact:N" to select the Nth contact from a previous ambiguous match
                  For group chats, use the chat ID from tool_get_chats (e.g., "chat123456789")
        message: Message text to send
        group_chat: Whether this is a group chat (uses chat ID instead of buddy)

    Returns:
        Success or error message
    """
    # Convert to string to ensure phone numbers work properly
    recipient = str(recipient).strip()

    # For group chats, skip contact lookup and use the chat ID directly
    if group_chat:
        # Use the recipient directly as the chat ID
        return _send_message_to_recipient(recipient, message, group_chat=True)

    # Handle contact selection format (contact:N)
    if recipient.lower().startswith("contact:"):
        try:
            # Get the selected index (1-based)
            index = int(recipient.split(":", 1)[1].strip()) - 1

            # Get the most recent contact matches from global cache
            if (
                not hasattr(send_message, "recent_matches")
                or not send_message.recent_matches
            ):
                return "No recent contact matches available. Please search for a contact first."

            if index < 0 or index >= len(send_message.recent_matches):
                return f"Invalid selection. Please choose a number between 1 and {len(send_message.recent_matches)}."

            # Get the selected contact
            contact = send_message.recent_matches[index]
            return _send_message_to_recipient(
                contact["phone"], message, contact["name"], group_chat=False
            )
        except (ValueError, IndexError) as e:
            return f"Error selecting contact: {str(e)}"

    # Check if recipient is directly a phone number.
    if _looks_like_phone_input(recipient):
        formatted_number = _format_phone_for_messages(recipient)
        if not formatted_number:
            return (
                f"Error: '{recipient}' is not a usable phone number for region "
                f"{get_default_region()}. Use an E.164 number such as "
                "+14155551234, or set MAC_MESSAGES_REGION if your national "
                "numbers belong to another region."
            )
        return _send_message_to_recipient(formatted_number, message, group_chat=False)

    # Check if recipient is an email address
    if "@" in recipient:
        return _send_message_to_recipient(recipient, message, group_chat=False)

    # Try to find the contact by name
    contacts = find_contact_by_name(recipient)

    if not contacts:
        return f"Error: Could not find any contact matching '{recipient}'"

    if len(contacts) == 1:
        # Single match, use it
        contact = contacts[0]
        return _send_message_to_recipient(
            contact["phone"], message, contact["name"], group_chat=False
        )
    else:
        # Store the matches for later selection
        send_message.recent_matches = contacts

        # Multiple matches, return them all
        contact_list = "\n".join(
            [
                f"{i+1}. {neutralize_untrusted_text(c['name'])} "
                f"({neutralize_untrusted_text(c['phone'])})"
                for i, c in enumerate(contacts[:10])
            ]
        )
        return (
            f"Multiple contacts found matching "
            f"'{neutralize_untrusted_text(recipient)}'. Please specify which one "
            f"using 'contact:N' where N is the number:\n{contact_list}"
        )


# Initialize the static variable for recent matches
send_message.recent_matches = []


APPLE_EPOCH_OFFSET = 978307200  # seconds between the unix epoch and 2001-01-01


def _candidate_handles(recipient: str) -> List[str]:
    """
    Build the set of handle ids the Messages database might have recorded
    for this recipient (email as-is; phone numbers in several formats).
    """
    return handle_variants(recipient)


def _row_text(row: Dict[str, Any]) -> Optional[str]:
    """Best-effort plain text for a message row (`text` column, else attributedBody)."""
    text = row.get("text")
    if text:
        return text
    return extract_body_from_attributed(row.get("attributedBody"))


def _verify_send_in_db(
    recipient: str,
    sent_after_unix: float,
    message_text: Optional[str] = None,
    timeout: float = 6.0,
) -> Optional[Dict[str, Any]]:
    """
    Poll the Messages database for the outbound message to `recipient`
    recorded after `sent_after_unix`.

    The AppleScript `send` command returns without error even when the
    message later fails (e.g. error 22 for an unroutable handle, or a
    recipient who deregistered from iMessage), so the AppleScript result
    alone cannot confirm a send. The authoritative outcome lives in
    chat.db's message.error / message.is_sent columns, which are populated
    within a second or two of the attempt.

    `sent_after_unix` alone is not a reliable correlation key: two sends to
    the same handle close together (e.g. rapid-fire tool calls) can both be
    "the latest row after time X" from either call's point of view, so a
    plain `ORDER BY date DESC LIMIT 1` can report the outcome of the wrong
    message. When `message_text` is given, matching rows are additionally
    filtered by exact body match (decoding attributedBody when `text` is
    NULL) so each call correlates to *its own* send rather than whichever
    row happens to be newest. If nothing matches the body (e.g. Messages
    re-encoded the text, or the row only has an attachment), we fall back to
    the plain latest-row behavior rather than reporting a false negative.

    Returns the row (guid, error, is_sent, is_delivered, service), or None
    if no row could be read before the timeout (e.g. no Full Disk Access).
    """
    apple_ns = int((sent_after_unix - APPLE_EPOCH_OFFSET - 1) * 1_000_000_000)

    def _matching_rows(handles: List[str]) -> List[Dict[str, Any]]:
        placeholders = ", ".join("?" for _ in handles)
        # m.error is aliased to send_error so a real row can't be mistaken
        # for query_messages_db's {"error": ...} failure dict.
        query = f"""
            SELECT m.guid, m.error AS send_error, m.is_sent, m.is_delivered,
                   m.service, m.text, m.attributedBody
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.is_from_me = 1
              AND h.id IN ({placeholders})
              AND m.date >= ?
            ORDER BY m.date DESC
            LIMIT 10
        """
        results = query_messages_db(query, tuple(handles) + (apple_ns,))
        if results and "guid" in results[0]:
            return results
        return []

    def _best_row(handles: List[str]) -> Optional[Dict[str, Any]]:
        rows = _matching_rows(handles)
        if not rows:
            return None
        if message_text is not None:
            for row in rows:
                if _row_text(row) == message_text:
                    return row
            # No row's body matched this send -- fall back to the newest row
            # rather than reporting nothing (e.g. attachment-only messages,
            # or Messages normalizing the text on write).
        return rows[0]

    exact = [recipient.strip()]
    variants = _candidate_handles(recipient)
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        # Prefer the exact handle the send targeted; only widen to format
        # variants when the exact handle has no row (Messages sometimes
        # records the handle in a different format than it was given).
        row = _best_row(exact) or _best_row(variants)
        if row is not None:
            # Stop polling once the row resolves: an error code appears, or
            # the message is marked sent. Otherwise keep waiting.
            if row.get("send_error") or row.get("is_sent"):
                return row
        time.sleep(0.5)
    return row


def _report_send_outcome(
    recipient: str,
    display_name: str,
    service: str,
    sent_after_unix: float,
    message_text: Optional[str] = None,
) -> str:
    """
    Turn the database verification result into the string returned to the
    caller. Never claims success for a message the database says failed.
    """
    display_name = neutralize_untrusted_text(display_name)
    row = _verify_send_in_db(recipient, sent_after_unix, message_text)
    if row is None:
        # Could not read the database (or the row never appeared); report
        # honestly instead of claiming success.
        return (
            f"Message to {display_name} was handed to Messages.app via {service}, "
            f"but delivery could not be verified in the Messages database."
        )
    actual_service = row.get("service") or service
    if row.get("send_error"):
        return (
            f"Error: message to {display_name} failed to send "
            f"(Messages error code {row['send_error']}, service {actual_service}). "
            f"The recipient may not be reachable via {actual_service}."
        )
    status = "delivered" if row.get("is_delivered") else "sent"
    return f"Message {status} successfully via {actual_service} to {display_name}"


def _send_message_to_recipient(
    recipient: str, message: str, contact_name: str = None, group_chat: bool = False
) -> str:
    """
    Internal function to send a message to a specific recipient using file-based approach.

    Args:
        recipient: Phone number or email
        message: Message text to send
        contact_name: Optional contact name for the success message
        group_chat: Whether this is a group chat

    Returns:
        Success or error message
    """
    safe_recipient = escape_applescript(recipient)
    file_path = None
    try:
        # Owner-only temp file (mkstemp is 0o600). NamedTemporaryFile is
        # world-readable on some systems and is flagged as CWE-377.
        fd, file_path = tempfile.mkstemp(prefix="mac-messages-", suffix=".txt")
        try:
            os.write(fd, message.encode("utf-8"))
        finally:
            os.close(fd)
        safe_file_path = escape_applescript(file_path)

        # Adjust the AppleScript command based on whether this is a group chat
        if not group_chat:
            command = f'tell application "Messages" to send (read (POSIX file "{safe_file_path}") as «class utf8») to participant "{safe_recipient}" of (1st service whose service type = iMessage)'
        else:
            # Group chats are addressed by their full chat id (e.g. "iMessage;+;chat123…").
            # The Messages dictionary requires `chat id "…"`, NOT `chat "…"`:
            # the latter looks up by the chat's display name and fails for guid-style
            # identifiers (raises -1728 "Can't get chat …").
            command = f'tell application "Messages" to send (read (POSIX file "{safe_file_path}") as «class utf8») to chat id "{safe_recipient}"'

        sent_at = time.time()

        # Run the AppleScript
        result = run_applescript(command)

        # Check result
        if result.startswith("Error:"):
            # Try fallback to direct method
            return _send_message_direct(recipient, message, contact_name, group_chat)

        # AppleScript accepted the send; confirm the outcome in the database
        display_name = neutralize_untrusted_text(
            contact_name if contact_name else recipient
        )
        if group_chat:
            # Group chat ids can't be verified against a single handle
            return f"Message sent successfully to {display_name}"
        return _report_send_outcome(
            recipient, display_name, "iMessage", sent_at, message
        )
    except Exception as e:
        # Try fallback method
        return _send_message_direct(recipient, message, contact_name, group_chat)
    finally:
        # Clean up the temporary file
        if file_path:
            try:
                os.remove(file_path)
            except OSError:
                pass


def get_contact_name(handle_id: int) -> str:
    """
    Get contact name from handle_id with improved contact lookup.
    """
    if handle_id is None:
        return "Unknown"

    # First, get the phone number or email
    handle_query = """
    SELECT id FROM handle WHERE ROWID = ?
    """
    handles = query_messages_db(handle_query, (handle_id,))

    if not handles or "error" in handles[0]:
        return "Unknown"

    handle_id_value = handles[0]["id"]

    # Try to match with AddressBook contacts
    contacts = get_cached_contacts()

    # Both sides of this comparison are canonical, so a handle recorded as
    # "+33639980001" matches an address book entry written "06 39 98 00 01"
    # without having to enumerate country-code variations by hand. The extra
    # keys cover the address book entries that could not be canonicalized and
    # so are stored under their digits.
    for key in lookup_keys(handle_id_value):
        if key in contacts:
            return contacts[key]

    # If no match found in AddressBook, fall back to display name from chat
    contact_query = """
    SELECT 
        c.display_name 
    FROM 
        handle h
    JOIN 
        chat_handle_join chj ON h.ROWID = chj.handle_id
    JOIN 
        chat c ON chj.chat_id = c.ROWID
    WHERE 
        h.id = ? 
    LIMIT 1
    """

    contacts = query_messages_db(contact_query, (handle_id_value,))

    if (
        contacts
        and len(contacts) > 0
        and "display_name" in contacts[0]
        and contacts[0]["display_name"]
    ):
        return contacts[0]["display_name"]

    # If no contact name found, return the phone number or email
    return handle_id_value


def _find_chat_by_identifier(chat_id: str) -> Optional[Dict[str, Any]]:
    """Find a Messages chat row by chat_identifier or room_name."""
    chat_id = str(chat_id).strip()
    if not chat_id:
        return None

    variants = {chat_id}
    if chat_id.startswith("chat"):
        variants.add(f"iMessage;-;{chat_id}")
        variants.add(f"iMessage;+;{chat_id}")
    elif chat_id.startswith("iMessage;"):
        short_id = chat_id.rsplit(";", 1)[-1]
        if short_id.startswith("chat"):
            variants.add(short_id)

    placeholders = ", ".join(["?" for _ in variants])
    query = f"""
    SELECT ROWID, display_name, chat_identifier, room_name
    FROM chat
    WHERE chat_identifier IN ({placeholders})
       OR room_name IN ({placeholders})
    LIMIT 1
    """
    params = tuple(variants) + tuple(variants)
    rows = query_messages_db(query, params)
    if not rows or "error" in rows[0]:
        return None
    return rows[0]


@bound_untrusted_output
def get_recent_messages(
    hours: int = 24,
    contact: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> str:
    """
    Get recent messages from the Messages app using attributedBody for content.

    Args:
        hours: Number of hours to look back (default: 24)
        contact: Filter by contact name, phone number, or email (optional)
                Use "contact:N" to select a specific contact from previous matches
        chat_id: Filter by group chat identifier from tool_get_chats (optional)

    Returns:
        Formatted string with recent messages
    """
    # Input validation
    if hours < 0:
        return "Error: Hours cannot be negative. Please provide a positive number."

    # Prevent integer overflow - limit to reasonable maximum (10 years)
    MAX_HOURS = 10 * 365 * 24  # 87,600 hours
    if hours > MAX_HOURS:
        return f"Error: Hours value too large. Maximum allowed is {MAX_HOURS} hours (10 years)."

    if contact and chat_id:
        return "Error: Provide either contact or chat_id, not both."

    handle_ids = None
    chat_row_id = None
    chat_display_name = None

    if chat_id:
        chat_id = str(chat_id).strip()
        if not chat_id:
            return "Error: chat_id cannot be empty."
        chat = _find_chat_by_identifier(chat_id)
        if not chat:
            return f"No group chat found with chat_id '{chat_id}'. Use tool_get_chats to list available group chats."
        chat_row_id = chat["ROWID"]
        chat_display_name = chat.get("display_name") or chat_id

    # If contact is specified, try to resolve it
    if contact:
        # Convert to string to ensure phone numbers work properly
        contact = str(contact).strip()

        # Handle contact selection format (contact:N)
        if contact.lower().startswith("contact:"):
            try:
                # Extract the number after the colon
                contact_parts = contact.split(":", 1)
                if len(contact_parts) < 2 or not contact_parts[1].strip():
                    return "Error: Invalid contact selection format. Use 'contact:N' where N is a positive number."

                # Get the selected index (1-based)
                try:
                    index = int(contact_parts[1].strip()) - 1
                except ValueError:
                    return "Error: Contact selection must be a number. Use 'contact:N' where N is a positive number."

                # Validate index is not negative
                if index < 0:
                    return "Error: Contact selection must be a positive number (starting from 1)."

                # Get the most recent contact matches from global cache
                if (
                    not hasattr(get_recent_messages, "recent_matches")
                    or not get_recent_messages.recent_matches
                ):
                    return "No recent contact matches available. Please search for a contact first."

                if index >= len(get_recent_messages.recent_matches):
                    return f"Invalid selection. Please choose a number between 1 and {len(get_recent_messages.recent_matches)}."

                # Get the selected contact's phone number
                contact = get_recent_messages.recent_matches[index]["phone"]
            except Exception as e:
                return f"Error processing contact selection: {str(e)}"

        # Check if contact might be a name rather than a phone number or email
        # If any character is NOT a phone/email character, treat as a name.
        # An address is named explicitly: it carries letters, so it would
        # otherwise be sent to fuzzy name matching, which returns "No contacts
        # found" for anyone whose address is not in the address book and never
        # reaches the handle lookup below.
        if not is_email_handle(contact) and not all(
            c.isdigit() or c in "+- ()@." for c in contact
        ):
            # Try fuzzy matching
            matches = find_contact_by_name(contact)

            if not matches:
                return f"No contacts found matching '{contact}'."

            if len(matches) == 1:
                # Single match, use its phone number
                contact = matches[0]["phone"]
            else:
                # Store the matches for later selection
                get_recent_messages.recent_matches = matches

                # Multiple matches, return them all
                contact_list = "\n".join(
                    [
                        f"{i+1}. {c['name']} ({c['phone']})"
                        for i, c in enumerate(matches[:10])
                    ]
                )
                return (
                    f"Multiple contacts found matching '{contact}'. Please specify "
                    f"which one using 'contact:N' where N is the number:\n{contact_list}"
                )

        # At this point, contact should be a phone number or email
        # Try to find handle_ids with improved phone number matching
        if "@" in contact:
            # This is an email. Fold the case on both sides: handle.id compares
            # case-sensitively, and the canonical form is lowercased.
            query = "SELECT ROWID FROM handle WHERE id = ? COLLATE NOCASE"
            results = query_messages_db(
                query, (canonical_handle(contact) or contact.strip(),)
            )
            if results and not "error" in results[0] and len(results) > 0:
                handle_ids = [row["ROWID"] for row in results]
        else:
            # This is a phone number - try various formats (returns all handles for multi-protocol)
            handle_ids = find_handles_by_phone(contact)

        if not handle_ids:
            # Try a direct search in message table to see if any messages exist.
            # Match on the digits of the canonical number so that a national
            # input still finds a handle stored in international format.
            normalized = digits_only(canonical_handle(contact) or contact)
            query = """
            SELECT COUNT(*) as count 
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE h.id LIKE ?
            """
            results = query_messages_db(query, (f"%{normalized}%",))

            if (
                results
                and not "error" in results[0]
                and results[0].get("count", 0) == 0
            ):
                # No messages found but the query was valid
                return f"No message history found with '{contact}'."
            else:
                # Could not find the handle at all
                return f"Could not find any messages with contact '{contact}'. Verify the phone number or email is correct."

    # Calculate the timestamp for X hours ago
    hours_ago = datetime.now(timezone.utc) - timedelta(hours=hours)
    # String-bind the Apple-ns timestamp to avoid SQLite integer overflow.
    timestamp_str = str(_to_apple_ns(hours_ago))

    # Build the SQL query - use attributedBody field and text
    query = """
    SELECT 
        m.ROWID,
        m.date, 
        m.text, 
        m.attributedBody,
        m.is_from_me,
        m.handle_id,
        m.cache_roomnames
    FROM 
        message m
    WHERE 
        CAST(m.date AS TEXT) > ? 
    """

    params = [timestamp_str]

    # Add contact filter if handle_ids were found (support multiple handles for multi-protocol)
    if handle_ids:
        placeholders = ", ".join(["?" for _ in handle_ids])
        query += f"AND m.handle_id IN ({placeholders}) "
        params.extend(handle_ids)

    if chat_row_id is not None:
        query += "AND m.ROWID IN (SELECT message_id FROM chat_message_join WHERE chat_id = ?) "
        params.append(chat_row_id)

    query += "ORDER BY m.date DESC LIMIT 100"

    # Execute the query
    messages = query_messages_db(query, tuple(params))

    # Format the results
    if not messages:
        return "No messages found in the specified time period."

    if "error" in messages[0]:
        return f"Error accessing messages: {messages[0]['error']}"

    # Get chat mapping for group chat names
    chat_mapping = get_chat_mapping()

    # Bulk-fetch attachments for all message ROWIDs in one query (Tier 1 progressive disclosure).
    visible_ids = [msg["ROWID"] for msg in messages if msg.get("ROWID") is not None]
    attachments_by_msg = _attachments_for_message_ids(visible_ids)

    formatted_messages = []
    for msg in messages:
        # Get the message content from text or attributedBody
        if msg.get("text"):
            body = msg["text"]
        elif msg.get("attributedBody"):
            body = extract_body_from_attributed(msg["attributedBody"])
            if not body:
                # Skip messages with no content
                continue
        else:
            # Skip empty messages
            continue

        # Convert Apple timestamp to readable date
        try:
            date_val = _from_apple_ns(int(msg["date"]))
            date_str = date_val.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OverflowError) as e:
            # If conversion fails, use a placeholder
            date_str = "Unknown date"
            print(f"Date conversion error: {e} for timestamp {msg['date']}")

        direction = "You" if msg["is_from_me"] else get_contact_name(msg["handle_id"])

        # Check if this is a group chat
        group_chat_name = None
        if msg.get("cache_roomnames"):
            group_chat_name = chat_mapping.get(msg["cache_roomnames"])
        if not group_chat_name and chat_display_name:
            group_chat_name = chat_display_name

        message_prefix = f"[{date_str}]"
        if group_chat_name:
            message_prefix += f" [{group_chat_name}]"

        attachment_summary = _format_attachment_summary(
            attachments_by_msg.get(msg["ROWID"], [])
        )
        body = _sanitize_message_body(body)
        formatted_messages.append(
            f"{message_prefix} {direction}: {body}{attachment_summary}"
        )

    if not formatted_messages:
        return "No messages found in the specified time period."

    return "\n".join(formatted_messages)


# Initialize the static variable for recent matches
get_recent_messages.recent_matches = []


# Maximum number of messages returned by a single fuzzy search query.
# A soft cap — if hit, the user is told results were truncated.
_FUZZY_SEARCH_SOFT_CAP = 10_000


def _escape_like(term: str) -> str:
    """Escape SQL LIKE wildcards so the term is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@bound_untrusted_output
def fuzzy_search_messages(
    search_term: str,
    hours: int = 720,
    threshold: float = 0.6,  # Default threshold adjusted for thefuzz
) -> str:
    """
    Fuzzy search for messages containing the search_term within the last N hours.

    Args:
        search_term: The string to search for in message content.
        hours: Number of hours to look back (default: 720, i.e. 30 days).
               Use 0 to search all messages with no time limit.
        threshold: Minimum similarity score (0.0-1.0) to consider a match (default: 0.6 for WRatio).
                   A lower threshold allows for more lenient matching.

    Returns:
        Formatted string with matching messages and their scores, or an error/no results message.
    """
    # Input validation
    if not search_term or not search_term.strip():
        return "Error: Search term cannot be empty."

    if hours < 0:
        return "Error: Hours cannot be negative. Please provide a positive number."

    # Prevent integer overflow - limit to reasonable maximum (10 years)
    MAX_HOURS = 10 * 365 * 24  # 87,600 hours
    if hours > MAX_HOURS:
        return f"Error: Hours value too large. Maximum allowed is {MAX_HOURS} hours (10 years)."

    if not (0.0 <= threshold <= 1.0):
        return "Error: Threshold must be between 0.0 and 1.0."

    # Build the SQL query — use a LIKE pre-filter on the text column to let
    # SQLite do the heavy lifting for exact substring matches.  Messages
    # stored only in attributedBody (binary blob) cannot be LIKE-searched,
    # so we also fetch those and filter in Python.
    escaped_term = _escape_like(search_term)
    like_param = f"%{escaped_term}%"

    like_clause = "(m.text LIKE ? ESCAPE '\\' OR (m.text IS NULL AND m.attributedBody IS NOT NULL))"
    where_clauses = [like_clause]
    params_list = [like_param]

    if hours == 0:
        time_desc = "all time"
    else:
        hours_ago_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        # String-bind the Apple-ns timestamp to avoid SQLite integer overflow.
        timestamp_str = str(_to_apple_ns(hours_ago_dt))

        where_clauses.insert(0, "CAST(m.date AS TEXT) > ?")
        params_list.insert(0, timestamp_str)
        time_desc = f"the last {hours} hours"

    params_list.append(_FUZZY_SEARCH_SOFT_CAP)
    where_sql = " AND ".join(where_clauses)
    query = f"""
    SELECT
        m.ROWID,
        m.date,
        m.text,
        m.attributedBody,
        m.is_from_me,
        m.handle_id,
        m.cache_roomnames
    FROM
        message m
    WHERE
        {where_sql}
    ORDER BY m.date DESC
    LIMIT ?
    """
    params = tuple(params_list)

    raw_messages = query_messages_db(query, params)

    if not raw_messages:
        return f"No messages found in {time_desc} to search."
    if "error" in raw_messages[0]:
        return f"Error accessing messages: {raw_messages[0]['error']}"

    message_candidates = []
    for msg_dict in raw_messages:
        body = msg_dict.get("text") or extract_body_from_attributed(
            msg_dict.get("attributedBody")
        )
        if body and body.strip():
            message_candidates.append((body, msg_dict))

    if not message_candidates:
        return f"No message content found to search in {time_desc}."

    # --- Two-pass matching: exact substring first, then fuzzy ---
    cleaned_search_term = _clean_text(search_term).lower()
    # thefuzz scores are 0-100. Scale the input threshold (0.0-1.0).
    scaled_threshold = threshold * 100

    matched_messages_with_scores = []
    for original_message_text, msg_dict_value in message_candidates:
        cleaned_candidate_text = _clean_text(original_message_text).lower()

        # Pass 1: exact substring match gets a perfect score
        if cleaned_search_term in cleaned_candidate_text:
            score_normalised = 1.0
        else:
            # Pass 2: fuzzy match via WRatio
            score_from_thefuzz = fuzz.WRatio(
                cleaned_search_term, cleaned_candidate_text
            )
            if score_from_thefuzz < scaled_threshold:
                continue
            score_normalised = score_from_thefuzz / 100.0

        matched_messages_with_scores.append(
            (original_message_text, msg_dict_value, score_normalised)
        )

    matched_messages_with_scores.sort(
        key=lambda x: x[2], reverse=True
    )  # Sort by score desc

    if not matched_messages_with_scores:
        return f"No messages found matching '{search_term}' with a threshold of {threshold} in {time_desc}."

    truncated = len(raw_messages) >= _FUZZY_SEARCH_SOFT_CAP

    chat_mapping = get_chat_mapping()

    # Bulk-fetch attachments for all matched message ROWIDs (Tier 1 progressive disclosure).
    matched_ids = [
        m[1]["ROWID"]
        for m in matched_messages_with_scores
        if m[1].get("ROWID") is not None
    ]
    attachments_by_msg = _attachments_for_message_ids(matched_ids)

    formatted_results = []
    for _matched_text, msg_dict, score in matched_messages_with_scores:
        original_body = (
            msg_dict.get("text")
            or extract_body_from_attributed(msg_dict.get("attributedBody"))
            or "[No displayable content]"
        )

        date_val = _from_apple_ns(int(msg_dict["date"]))
        date_str = date_val.astimezone().strftime("%Y-%m-%d %H:%M:%S")

        direction = (
            "You" if msg_dict["is_from_me"] else get_contact_name(msg_dict["handle_id"])
        )
        group_chat_name = (
            chat_mapping.get(msg_dict.get("cache_roomnames"))
            if msg_dict.get("cache_roomnames")
            else None
        )
        message_prefix = f"[{date_str}] (Score: {score:.2f})" + (
            f" [{group_chat_name}]" if group_chat_name else ""
        )
        attachment_summary = _format_attachment_summary(
            attachments_by_msg.get(msg_dict.get("ROWID"), [])
        )
        original_body = _sanitize_message_body(original_body)
        formatted_results.append(
            f"{message_prefix} {direction}: {original_body}{attachment_summary}"
        )

    header = f"Found {len(matched_messages_with_scores)} messages matching '{search_term}':\n"
    if truncated:
        header += (
            f"(Results capped at {_FUZZY_SEARCH_SOFT_CAP} messages — "
            "try a shorter time window for more precise results.)\n"
        )
    return header + "\n".join(formatted_results)


def _check_imessage_availability(recipient: str) -> bool:
    """
    Check if recipient has iMessage available by querying the messages database.

    Args:
        recipient: Phone number or email to check

    Returns:
        True if iMessage is available, False otherwise
    """
    if is_email_handle(recipient):
        # handle.id has no declared collation, so it compares case-sensitively
        # while the canonical form is lowercased. Fold both sides instead of
        # only the input, or an address stored in mixed case stops matching the
        # mixed-case spelling that used to find it.
        query_params = (canonical_handle(recipient) or recipient.strip(),)
        where_clause = "h.id = ? COLLATE NOCASE"
    else:
        # Resolve through the same canonical matching the message lookup uses,
        # so a number that has iMessage history is not reported as SMS-only
        # just because it is written differently from the stored handle.
        handle_rowids = find_handles_by_phone(recipient)

        if not handle_rowids:
            return False

        query_params = tuple(handle_rowids)
        placeholders = ", ".join(["?" for _ in query_params])
        where_clause = f"h.ROWID IN ({placeholders})"

    query = f"""
        SELECT
            h.ROWID,
            h.service,
            COUNT(m.guid) as text_count,
            COUNT(CASE WHEN m.error != 0 then 1 END) as errors
        FROM handle h
        LEFT JOIN message m ON h.ROWID = m.handle_id
        WHERE {where_clause}
        GROUP BY
            h.ROWID,
            h.service
        """

    result = query_messages_db(query, query_params)

    if not result or "error" in result[0]:
        return False

    for row in result:
        service_type = row.get("service", "")
        text_count = row.get("text_count", 0)
        num_errors = row.get("errors", 0)

        # Only count as iMessage available if there were successful messages (errors < total)
        if num_errors < text_count:
            if service_type in ("iMessage", "iMessageLite"):
                return True

    return False


def _send_message_sms(recipient: str, message: str, contact_name: str = None) -> str:
    """
    Send message via SMS/RCS using AppleScript.

    Args:
        recipient: Phone number to send to
        message: Message content
        contact_name: Optional contact name for display

    Returns:
        Success or error message
    """
    safe_message = escape_applescript(message)
    safe_recipient = escape_applescript(recipient)

    script = f"""
    tell application "Messages"
        try
            -- Try to find SMS service
            set smsService to first account whose service type = SMS and enabled is true
            
            -- Send message via SMS
            send "{safe_message}" to participant "{safe_recipient}" of smsService
            
            -- Wait briefly to check for immediate errors
            delay 1
            
            return "success"
        on error errMsg
            return "error:" & errMsg
        end try
    end tell
    """

    try:
        sent_at = time.time()
        result = run_applescript(script)
        if result.startswith("error:"):
            return f"Error sending SMS: {result[6:]}"
        elif result.strip() == "success":
            display_name = contact_name if contact_name else recipient
            return _report_send_outcome(
                recipient, display_name, "SMS", sent_at, message
            )
        else:
            return f"Unknown SMS result: {result}"
    except Exception as e:
        return f"Error sending SMS: {str(e)}"


def _send_message_direct(
    recipient: str, message: str, contact_name: str = None, group_chat: bool = False
) -> str:
    """
    Enhanced direct AppleScript method for sending messages with SMS/RCS fallback.

    This function implements automatic fallback from iMessage to SMS/RCS when:
    1. Recipient doesn't have iMessage
    2. iMessage delivery fails
    3. iMessage service is unavailable

    Args:
        recipient: Phone number or email
        message: Message content
        contact_name: Optional contact name for display
        group_chat: Whether this is a group chat

    Returns:
        Success or error message with service type used
    """
    # Clean the inputs for AppleScript using the central helper, which also
    # handles newlines, tabs, and Unicode line/paragraph separators.
    safe_message = escape_applescript(message)
    safe_recipient = escape_applescript(recipient)

    # For group chats, stick to iMessage only (SMS doesn't support group chats well)
    if group_chat:
        script = f"""
        tell application "Messages"
            try
                -- Try to get the existing chat by its full id (e.g. "iMessage;+;chat123…").
                -- `chat id "…"` looks up by guid; plain `chat "…"` looks up by display
                -- name and fails on guid-style identifiers with -1728 "Can't get chat".
                set targetChat to chat id "{safe_recipient}"
                
                -- Send the message
                send "{safe_message}" to targetChat
                
                -- Wait briefly to check for immediate errors
                delay 1
                
                -- Return success
                return "success"
            on error errMsg
                -- Chat method failed
                return "error:" & errMsg
            end try
        end tell
        """

        try:
            result = run_applescript(script)
            if result.startswith("error:"):
                return f"Error sending group message: {result[6:]}"
            elif result.strip() == "success":
                display_name = neutralize_untrusted_text(
                    contact_name if contact_name else recipient
                )
                return f"Group message sent successfully to {display_name}"
            else:
                return f"Unknown group message result: {result}"
        except Exception as e:
            return f"Error sending group message: {str(e)}"

    # For individual messages, try iMessage first with automatic SMS fallback
    # Enhanced AppleScript with built-in fallback logic
    script = f"""
    tell application "Messages"
        try
            -- First, try iMessage
            set targetService to 1st service whose service type = iMessage
            
            try
                -- Try to get the existing participant if possible
                set targetBuddy to participant "{safe_recipient}" of targetService
                
                -- Send the message via iMessage
                send "{safe_message}" to targetBuddy
                
                -- Wait briefly to check for immediate errors
                delay 2
                
                -- Return success with service type
                return "success:iMessage"
            on error iMessageErr
                -- iMessage failed, try SMS fallback if recipient looks like a phone number
                try
                    -- Check if recipient looks like a phone number (contains digits)
                    if "{safe_recipient}" contains "0" or "{safe_recipient}" contains "1" or "{safe_recipient}" contains "2" or "{safe_recipient}" contains "3" or "{safe_recipient}" contains "4" or "{safe_recipient}" contains "5" or "{safe_recipient}" contains "6" or "{safe_recipient}" contains "7" or "{safe_recipient}" contains "8" or "{safe_recipient}" contains "9" then
                        -- Try SMS service
                        set smsService to first account whose service type = SMS and enabled is true
                        send "{safe_message}" to participant "{safe_recipient}" of smsService
                        
                        -- Wait briefly to check for immediate errors
                        delay 2
                        
                        return "success:SMS"
                    else
                        -- Not a phone number, can't use SMS
                        return "error:iMessage failed and SMS not available for email addresses - " & iMessageErr
                    end if
                on error smsErr
                    -- Both iMessage and SMS failed
                    return "error:Both iMessage and SMS failed - iMessage: " & iMessageErr & " SMS: " & smsErr
                end try
            end try
        on error generalErr
            return "error:" & generalErr
        end try
    end tell
    """

    try:
        sent_at = time.time()
        result = run_applescript(script)
        display_name = contact_name if contact_name else recipient

        if result.startswith("error:"):
            return f"Error sending message: {result[6:]}"
        elif result.strip() == "success:iMessage":
            return _report_send_outcome(
                recipient, display_name, "iMessage", sent_at, message
            )
        elif result.strip() == "success:SMS":
            return _report_send_outcome(
                recipient, display_name, "SMS", sent_at, message
            )
        elif result.strip() == "success":
            return _report_send_outcome(
                recipient, display_name, "iMessage", sent_at, message
            )
        else:
            return f"Unknown result: {result}"
    except Exception as e:
        return f"Error sending message: {str(e)}"


def check_messages_db_access() -> str:
    """Check if the Messages database is accessible and return detailed information."""
    try:
        db_path = get_messages_db_path()
        status = []

        # Check if the file exists
        if not os.path.exists(db_path):
            return f"ERROR: Messages database not found at {db_path} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."

        status.append(f"Database file exists at: {db_path}")

        # Check file permissions
        try:
            with open(db_path, "rb") as f:
                # Just try to read a byte to confirm access
                f.read(1)
            status.append("File is readable")
        except PermissionError:
            return f"ERROR: Permission denied when trying to read {db_path}. Please grant Full Disk Access permission to your terminal application. PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
        except Exception as e:
            return f"ERROR: Unknown error reading file: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."

        # Try to connect to the database
        try:
            conn = _connect_sqlite_readonly(db_path)
            status.append("Successfully connected to database")

            # Test a simple query
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM sqlite_master")
            count = cursor.fetchone()[0]
            status.append(f"Database contains {count} tables")

            # Check if the necessary tables exist
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('message', 'handle', 'chat')"
            )
            tables = [row[0] for row in cursor.fetchall()]
            if "message" in tables and "handle" in tables:
                status.append("Required tables (message, handle) are present")
            else:
                status.append(
                    f"WARNING: Some required tables are missing. Found: {', '.join(tables)}"
                )

            conn.close()
        except sqlite3.OperationalError as e:
            return f"ERROR: Database connection error: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."

        return "\n".join(status)
    except Exception as e:
        return f"ERROR: Unexpected error during database access check: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."


def _get_phone_formats(recipient: str) -> List[str]:
    """
    Get the handle id formats a phone recipient may be stored under.

    Args:
        recipient: Phone recipient, in any format

    Returns:
        List of phone recipients in various formats, most canonical first.
        National-format numbers are expanded against the region this Mac is
        configured for rather than assumed to be North American.
    """
    return handle_variants(recipient)


def find_handle_by_phone(phone: str) -> Optional[int]:
    """
    Find a handle ID by phone number, trying various formats.
    Prioritizes direct message handles over group chat handles.

    Args:
        phone: Phone number in any format

    Returns:
        handle_id if found, None otherwise
    """
    handles = find_handles_by_phone(phone)
    if handles and len(handles) > 0:
        return handles[0]
    return None


def find_handles_by_phone(phone: str) -> Optional[List[int]]:
    """
    Find all handle IDs by phone number, trying various formats.
    Returns all handles for multi-protocol support (iMessage, SMS, RCS).

    Args:
        phone: Phone number in any format

    Returns:
        List of handle_id's if found, None otherwise
    """
    formats_to_try = _get_phone_formats(phone)
    if not formats_to_try:
        return None

    placeholders = ", ".join(["?" for _ in formats_to_try])

    # Finds all handle_id's associated with the number
    query = f"""
    SELECT
    ROWID
    FROM handle
    WHERE id IN ({placeholders})
    """

    results = query_messages_db(query, tuple(formats_to_try))

    if results and "error" not in results[0]:
        rowids = [row["ROWID"] for row in results]
        if rowids:
            return rowids

    # Nothing matched one of the shapes we can predict, so fall back to
    # comparing every handle on its canonical form. This catches numbers
    # Messages stored in a spelling the variant list does not anticipate.
    return _find_handles_by_canonical_form(phone)


def _find_handles_by_canonical_form(phone: str) -> Optional[List[int]]:
    """
    Find handle ROWIDs whose id is the same number as `phone`, whatever its format.

    Args:
        phone: Phone number in any format

    Returns:
        List of handle_id's if any handle reduces to the same E.164 number,
        None otherwise.

    Notes:
        Scans the whole handle table, which holds a few thousand rows at most,
        so this stays well under a millisecond per call once the canonical
        forms are cached. Only reached when the indexed lookup found nothing.
    """
    target = canonical_handle(phone)
    if not target:
        return None

    rows = query_messages_db("SELECT ROWID, id FROM handle")
    if not rows or "error" in rows[0]:
        return None

    rowids = [
        row["ROWID"] for row in rows if canonical_handle(row.get("id", "")) == target
    ]
    return rowids or None


def check_addressbook_access() -> str:
    """Check if the AddressBook database is accessible and return detailed information."""
    try:
        home_dir = os.path.expanduser("~")
        sources_path = os.path.join(
            home_dir, "Library/Application Support/AddressBook/Sources"
        )
        status = []

        # Check if the directory exists
        if not os.path.exists(sources_path):
            return f"ERROR: AddressBook Sources directory not found at {sources_path} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."

        status.append(f"AddressBook Sources directory exists at: {sources_path}")

        # Find database files
        db_paths = glob.glob(os.path.join(sources_path, "*/AddressBook-v22.abcddb"))

        if not db_paths:
            return f"ERROR: No AddressBook database files found in {sources_path} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."

        status.append(f"Found {len(db_paths)} AddressBook database files:")
        for path in db_paths:
            status.append(f" - {path}")

        # Check file permissions for each database
        for db_path in db_paths:
            try:
                with open(db_path, "rb") as f:
                    # Just try to read a byte to confirm access
                    f.read(1)
                status.append(f"File is readable: {db_path}")
            except PermissionError:
                status.append(
                    f"ERROR: Permission denied when trying to read {db_path} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
                )
                continue
            except Exception as e:
                status.append(
                    f"ERROR: Unknown error reading file {db_path}: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
                )
                continue

            # Try to connect to the database
            try:
                conn = _connect_sqlite_readonly(db_path)
                status.append(f"Successfully connected to database: {db_path}")

                # Test a simple query
                cursor = conn.cursor()
                cursor.execute("SELECT count(*) FROM sqlite_master")
                count = cursor.fetchone()[0]
                status.append(f"Database contains {count} tables")

                # Check if the necessary tables exist
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('ZABCDRECORD', 'ZABCDPHONENUMBER')"
                )
                tables = [row[0] for row in cursor.fetchall()]
                if "ZABCDRECORD" in tables and "ZABCDPHONENUMBER" in tables:
                    status.append(
                        "Required tables (ZABCDRECORD, ZABCDPHONENUMBER) are present"
                    )
                else:
                    status.append(
                        f"WARNING: Some required tables are missing. Found: {', '.join(tables)}"
                    )

                # Get a count of contacts
                try:
                    cursor.execute("SELECT COUNT(*) FROM ZABCDRECORD")
                    contact_count = cursor.fetchone()[0]
                    status.append(f"Database contains {contact_count} contacts")
                except sqlite3.OperationalError:
                    status.append(
                        "Could not query contact count PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
                    )

                conn.close()
            except sqlite3.OperationalError as e:
                status.append(
                    f"ERROR: Database connection error for {db_path}: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
                )

        # Try to get actual contacts
        contacts = get_addressbook_contacts()
        if contacts:
            status.append(
                f"Successfully retrieved {len(contacts)} contacts with phone numbers"
            )
        else:
            status.append(
                "WARNING: No contacts with phone numbers found. PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
            )

        return "\n".join(status)
    except Exception as e:
        return f"ERROR: Unexpected error during database access check: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

# UTI prefix that flags the iMessage app extension "balloon" payload format.
# These are container blobs (Apple Pay, polls, link previews, etc.) — not
# user-visible files, and parsing them is out of scope.
_PLUGIN_PAYLOAD_UTI_PREFIX = "com.apple.messages.MSMessageExtensionBalloonPlugin"

# MIME types we surface as inline image content rather than path metadata.
_INLINE_IMAGE_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
}

# Default cap on bytes returned inline. Above this we fall back to path
# metadata so we don't blow context on a 50MB video the model didn't ask for.
_DEFAULT_MAX_INLINE_BYTES = 5_000_000

_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _to_apple_ns(dt: datetime) -> int:
    """Convert a UTC datetime to Apple's nanoseconds-since-2001 format."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - _APPLE_EPOCH).total_seconds() * 1_000_000_000)


def _from_apple_ns(ts: int) -> datetime:
    """Convert an Apple-epoch ``message.date`` value to a UTC datetime.

    Older chat.db rows store seconds-since-2001 (10 or fewer digits in the
    integer); newer macOS versions store nanoseconds (more than 10 digits).
    Both are handled here so callers don't repeat the heuristic.
    """
    seconds = ts / 1_000_000_000 if len(str(ts)) > 10 else ts
    return _APPLE_EPOCH + timedelta(seconds=seconds)


def _resolve_attachment_path(filename: Optional[str]) -> Optional[str]:
    """Expand ~ and return an absolute path. Returns None for empty input."""
    if not filename:
        return None
    return os.path.expanduser(filename)


def _filter_excluded_attachments(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop stickers and plugin-payload rows. Keeps everything else."""
    kept = []
    for row in rows:
        if row.get("is_sticker"):
            continue
        uti = row.get("uti") or ""
        if uti.startswith(_PLUGIN_PAYLOAD_UTI_PREFIX):
            continue
        transfer_name = row.get("transfer_name") or ""
        if transfer_name.endswith(".pluginPayloadAttachment"):
            continue
        kept.append(row)
    return kept


def _shape_attachment(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a raw join row into the public metadata shape.

    chat.db's ``total_bytes`` is unreliable — many rows store a stale or
    rounded value (e.g. 1048576 for files that are actually 8MB). When the
    file is on disk we trust ``os.path.getsize`` instead.
    """
    path = _resolve_attachment_path(row.get("filename"))
    exists = bool(path) and os.path.exists(path)
    if exists:
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            size_bytes = row.get("total_bytes") or 0
    else:
        size_bytes = row.get("total_bytes") or 0
    return {
        "id": row["attachment_id"],
        "message_id": row["message_id"],
        "filename": row.get("transfer_name")
        or (os.path.basename(path) if path else None),
        "path": path,
        "mime_type": row.get("mime_type"),
        "uti": row.get("uti"),
        "size_bytes": size_bytes,
        "exists": exists,
    }


_ATTACHMENT_SELECT_COLS = """
    a.ROWID AS attachment_id,
    maj.message_id AS message_id,
    a.filename AS filename,
    a.transfer_name AS transfer_name,
    a.mime_type AS mime_type,
    a.uti AS uti,
    a.total_bytes AS total_bytes,
    a.is_sticker AS is_sticker,
    a.hide_attachment AS hide_attachment,
    a.created_date AS created_date
"""


def _format_attachment_summary(attachments: List[Dict[str, Any]]) -> str:
    """Compact one-line summary of a message's attachments — Tier 1 disclosure.

    Returns "" when the list is empty so callers can unconditionally append.
    The format keeps tokens low: id + mime_type per item, with the original
    filename only when distinct enough to be useful (small filenames help the
    agent disambiguate; we drop them past 3 attachments to cap the line).
    """
    if not attachments:
        return ""
    parts = []
    for att in attachments:
        mime = neutralize_untrusted_text(att.get("mime_type") or "?")
        # Filename helps when an agent is choosing between several attachments
        # on the same message; cap at 3 to keep the line short.
        if len(attachments) <= 3 and att.get("filename"):
            filename = neutralize_untrusted_text(att["filename"])
            parts.append(f"#{att['id']} {mime} ({filename})")
        else:
            parts.append(f"#{att['id']} {mime}")
    return f" [attachments: {', '.join(parts)}]"


def _attachments_for_message_ids(
    message_ids: List[int],
) -> Dict[int, List[Dict[str, Any]]]:
    """For a list of message ROWIDs, return a dict mapping each message id
    that has attachments to a list of attachment metadata dicts. Messages
    with no surviving (post-filter) attachments are absent from the dict."""
    if not message_ids:
        return {}

    placeholders = ",".join(["?"] * len(message_ids))
    query = f"""
        SELECT
            {_ATTACHMENT_SELECT_COLS},
            m.is_from_me AS is_from_me,
            m.handle_id AS handle_id
        FROM message_attachment_join maj
        JOIN attachment a ON a.ROWID = maj.attachment_id
        JOIN message m ON m.ROWID = maj.message_id
        WHERE maj.message_id IN ({placeholders})
        ORDER BY a.ROWID ASC
    """
    rows = query_messages_db(query, tuple(message_ids))
    if rows and "error" in rows[0]:
        return {}

    # Drop rows that don't look like attachment-join rows. Two reasons to
    # keep this guard: (1) in tests where a single query_messages_db mock
    # serves multiple queries, foreign rows would crash _shape_attachment;
    # (2) in production, a future schema change that adds an extra column
    # or strips one would degrade gracefully rather than break the tool.
    rows = [r for r in rows if "attachment_id" in r and "message_id" in r]
    rows = _filter_excluded_attachments(rows)

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        shaped = _shape_attachment(row)
        grouped.setdefault(row["message_id"], []).append(shaped)
    return grouped


@bound_untrusted_output
def search_attachments(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    contact: Optional[str] = None,
    mime_type: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    Search attachments across all messages by date range, contact, and MIME type.

    Returns metadata only — no file bytes. Use ``get_attachment(id)`` to fetch
    a specific file.

    Args:
        start_date: Inclusive ISO date "YYYY-MM-DD" (UTC). Optional.
        end_date: Inclusive ISO date "YYYY-MM-DD" (UTC). Optional.
        contact: Phone number, email, or contact name. Optional.
        mime_type: Prefix match e.g. "image/" or "application/pdf". Optional.
        limit: Maximum results to return (default 50).
    """
    if limit <= 0:
        return "Error: limit must be positive."

    where_clauses = []
    params: List[Any] = []

    if start_date:
        try:
            dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return f"Error: start_date must be YYYY-MM-DD, got '{start_date}'."
        where_clauses.append("CAST(m.date AS INTEGER) >= ?")
        params.append(_to_apple_ns(dt))

    if end_date:
        try:
            dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return f"Error: end_date must be YYYY-MM-DD, got '{end_date}'."
        # Inclusive: end of day
        dt_end = dt + timedelta(days=1)
        where_clauses.append("CAST(m.date AS INTEGER) < ?")
        params.append(_to_apple_ns(dt_end))

    if mime_type:
        # Caller can pass "image/" (prefix) or "image/jpeg" (exact). LIKE handles both.
        like_pattern = mime_type if "%" in mime_type else f"{mime_type}%"
        where_clauses.append("a.mime_type LIKE ?")
        params.append(like_pattern)

    handle_ids: Optional[List[int]] = None
    if contact:
        contact = str(contact).strip()
        # Reuse the same resolution logic the existing tools use, minus the
        # interactive contact:N selection (this is a non-interactive search tool).
        if "@" in contact:
            # Same case folding as the message lookup, see the note there.
            results = query_messages_db(
                "SELECT ROWID FROM handle WHERE id = ? COLLATE NOCASE",
                (canonical_handle(contact) or contact.strip(),),
            )
            if results and "error" not in results[0]:
                handle_ids = [r["ROWID"] for r in results]
        elif any(c.isdigit() for c in contact):
            handle_ids = find_handles_by_phone(contact)
        else:
            matches = find_contact_by_name(contact)
            if matches:
                resolved_handles = []
                for m in matches:
                    h = find_handles_by_phone(m["phone"]) or []
                    resolved_handles.extend(h)
                handle_ids = resolved_handles or None
        if not handle_ids:
            return f"No handles found for contact '{contact}'."
        placeholders = ",".join(["?"] * len(handle_ids))
        where_clauses.append(f"m.handle_id IN ({placeholders})")
        params.extend(handle_ids)

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
        SELECT
            {_ATTACHMENT_SELECT_COLS},
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
    # Pull a few extra rows so post-filter we can still hit `limit` cleanly.
    fetch_limit = limit * 3
    rows = query_messages_db(query, tuple(params + [fetch_limit]))

    if rows and "error" in rows[0]:
        return f"Error querying attachments: {rows[0]['error']}"

    rows = _filter_excluded_attachments(rows)
    rows = rows[:limit]

    if not rows:
        return "No attachments found matching the given filters."

    lines = [f"Found {len(rows)} attachment(s):"]
    for row in rows:
        shaped = _shape_attachment(row)
        try:
            date_str = (
                _from_apple_ns(int(row["message_date"]))
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S")
            )
        except (ValueError, TypeError, OverflowError):
            date_str = "Unknown date"
        sender = (
            "You" if row.get("is_from_me") else get_contact_name(row.get("handle_id"))
        )
        size_kb = (shaped["size_bytes"] or 0) / 1024
        marker = "" if shaped["exists"] else " [missing on disk]"
        lines.append(
            f"- id={shaped['id']} msg={shaped['message_id']} "
            f"[{date_str}] from {sender} | "
            f"{shaped['mime_type'] or 'unknown'} | "
            f"{shaped['filename'] or '(no name)'} | "
            f"{size_kb:.1f} KB{marker}"
        )

    lines.append("")
    lines.append(
        "Use tool_get_attachment(attachment_id=<id>) to fetch a specific file."
    )
    return "\n".join(lines)


def _heic_to_png_bytes(heic_bytes: bytes) -> Optional[bytes]:
    """Convert HEIC bytes to PNG bytes. Returns None if conversion isn't available
    on this machine (pillow-heif not installed or libheif missing)."""
    try:
        import io

        import pillow_heif  # type: ignore
        from PIL import Image as PILImage  # type: ignore

        pillow_heif.register_heif_opener()
        img = PILImage.open(io.BytesIO(heic_bytes))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return None


@bound_untrusted_output
def get_attachment(
    attachment_id: int,
    max_bytes: int = _DEFAULT_MAX_INLINE_BYTES,
):
    """
    Fetch a specific attachment by its ROWID.

    Always returns the resolved filesystem path so the human (or agent's
    filesystem tools) can act on the file directly — share it, save it,
    re-encode, attach elsewhere. Inline image bytes are a *bonus* added
    when the file is a supported image MIME type and fits under
    ``max_bytes``.

    Returns:
        - ``[metadata_text, Image]`` (list) for image MIME types under
          ``max_bytes`` (HEIC is converted to PNG inline if pillow-heif
          is available). The text always includes the absolute path.
        - ``str`` (metadata text only) for non-image types, missing files,
          oversized images, HEIC without pillow-heif, missing rows, and DB
          errors.
    """
    rows = query_messages_db(
        f"""
        SELECT
            {_ATTACHMENT_SELECT_COLS},
            m.is_from_me AS is_from_me,
            m.handle_id AS handle_id
        FROM message_attachment_join maj
        JOIN attachment a ON a.ROWID = maj.attachment_id
        JOIN message m ON m.ROWID = maj.message_id
        WHERE a.ROWID = ?
        LIMIT 1
        """,
        (attachment_id,),
    )

    if rows and "error" in rows[0]:
        return f"Error querying attachment: {rows[0]['error']}"
    if not rows:
        return f"Attachment {attachment_id} not found."

    row = rows[0]
    shaped = _shape_attachment(row)
    path = shaped["path"]
    mime = (shaped["mime_type"] or "").lower()

    if not path:
        return f"Attachment {attachment_id}: no filename recorded in database."

    if not os.path.exists(path):
        return (
            f"Attachment {attachment_id} ({shaped['filename']}, {mime or 'unknown'}): "
            f"missing on disk at {path}"
        )

    size_kb = (shaped["size_bytes"] or os.path.getsize(path)) / 1024
    metadata_text = (
        f"Attachment {attachment_id}: {mime or 'unknown'} | "
        f"{shaped['filename']} | {size_kb:.1f} KB | path: {path}"
    )

    # Non-image: path-only return so the caller can read with their own tools.
    if mime not in _INLINE_IMAGE_MIMES:
        return (
            f"{metadata_text}\n"
            f"This is not an image. Use your filesystem read tools on the path above."
        )

    # Oversize image: path-only, no inline bytes.
    actual_size = os.path.getsize(path)
    if actual_size > max_bytes:
        return (
            f"{metadata_text}\n"
            f"Image of {actual_size / 1024:.0f} KB exceeds max_bytes={max_bytes} — "
            f"inline render skipped. Read the file directly from path above, "
            f"or call again with a larger max_bytes."
        )

    with open(path, "rb") as f:
        raw = f.read()

    if mime in {"image/heic", "image/heif"}:
        png = _heic_to_png_bytes(raw)
        if png is None:
            return (
                f"{metadata_text}\n"
                f"HEIC image but pillow-heif is not available for conversion. "
                f"Install pillow-heif or read the file directly from path above."
            )
        return [metadata_text, Image(data=png, format="png")]

    fmt = mime.split("/", 1)[1] if "/" in mime else "png"
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in {"jpeg", "png", "gif", "webp"}:
        fmt = "png"
    return [metadata_text, Image(data=raw, format=fmt)]
