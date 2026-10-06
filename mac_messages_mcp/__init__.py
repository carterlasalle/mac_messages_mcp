"""Mac Messages MCP - A bridge for interacting with macOS Messages app"""

from importlib.metadata import PackageNotFoundError, version

from .messages import (
    check_addressbook_access,
    check_messages_db_access,
    find_contact_by_name,
    find_handle_by_phone,
    find_handles_by_phone,
    fuzzy_search_messages,
    get_addressbook_contacts,
    get_cached_contacts,
    get_contact_name,
    get_recent_messages,
    normalize_phone_number,
    query_addressbook_db,
    query_messages_db,
    send_message,
)

__all__ = [
    "check_addressbook_access",
    "check_messages_db_access",
    "find_contact_by_name",
    "find_handle_by_phone",
    "find_handles_by_phone",
    "fuzzy_search_messages",
    "get_addressbook_contacts",
    "get_cached_contacts",
    "get_contact_name",
    "get_recent_messages",
    "normalize_phone_number",
    "query_addressbook_db",
    "query_messages_db",
    "send_message",
]

try:
    __version__ = version("mac-messages-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
