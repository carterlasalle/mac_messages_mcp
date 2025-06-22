"""
Mac Messages MCP - A bridge for interacting with macOS Messages app
"""

from .messages import (
    check_addressbook_access,
    check_messages_db_access,
    find_contact_by_name,
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
    "get_recent_messages",
    "send_message",
    "query_messages_db",
    "get_contact_name",
    "check_messages_db_access",
    "get_addressbook_contacts",
    "normalize_phone_number",
    "get_cached_contacts",
    "query_addressbook_db",
    "check_addressbook_access",
    "find_contact_by_name",
    "fuzzy_search_messages",
]

__version__ = "0.7.2"
