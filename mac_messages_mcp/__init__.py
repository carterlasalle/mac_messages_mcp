"""
Mac Messages MCP - A bridge for interacting with macOS Messages app
"""

from .messages import (
    get_recent_messages, 
    send_message, 
    query_messages_db, 
    get_contact_name,
    check_messages_db_access,
    get_addressbook_contacts,
    normalize_phone_number,
    get_cached_contacts,
    query_addressbook_db,
    check_addressbook_access,
    find_contact_by_name
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
]

__version__ = "0.6.1"