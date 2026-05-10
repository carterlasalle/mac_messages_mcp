#!/usr/bin/env python3
"""
Mac Messages MCP - Entry point fixed for proper MCP protocol implementation
"""

import asyncio
import logging
import sys
from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from mac_messages_mcp.messages import (
    _check_imessage_availability,
    check_addressbook_access,
    check_messages_db_access,
    find_contact_by_name,
    fuzzy_search_messages,
    get_attachment,
    get_cached_contacts,
    get_recent_messages,
    query_messages_db,
    search_attachments,
    send_message,
)

# Configure logging to stderr for debugging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("mac_messages_mcp")

# Initialize the MCP server
mcp = FastMCP(
    "MessageBridge", instructions="A bridge for interacting with macOS Messages app"
)


@mcp.tool()
def tool_get_recent_messages(
    ctx: Context,
    hours: Annotated[
        int,
        Field(
            description=(
                "Number of hours to look back from now. Default 24, maximum 87600 "
                "(10 years)."
            ),
            ge=0,
            le=87600,
        ),
    ] = 24,
    contact: Annotated[
        str | None,
        Field(
            description=(
                "Optional contact filter: a contact name (fuzzy-matched in AddressBook), "
                "a phone number in E.164 with leading + (e.g. +14155551234), an email "
                'address, or "contact:N" from a previous contact match list.'
            )
        ),
    ] = None,
) -> str:
    """
    Read recent macOS Messages as a plain-text summary.

    This is read-only: it queries the local Messages database and does not send,
    edit, or delete messages. Requires macOS Full Disk Access for the host app or
    terminal. Returns sanitized message text, timestamps, participants, and compact
    attachment markers when files are present. Use this when you need chronological
    recent context; use tool_fuzzy_search_messages when searching for specific text,
    and tool_get_chats when you only need group chat IDs.
    """
    logger.info(f"Getting recent messages: hours={hours}, contact={contact}")
    try:
        # Handle contacts that are passed as numbers
        if contact is not None:
            contact = str(contact)
        result = get_recent_messages(hours=hours, contact=contact)
        return result
    except Exception as e:
        logger.error(f"Error in get_recent_messages: {str(e)}")
        return f"Error getting messages: {str(e)}"


@mcp.tool()
def tool_send_message(
    ctx: Context,
    recipient: Annotated[
        str,
        Field(
            description=(
                "Phone number in E.164 with leading + (e.g. +14155551234), email "
                "address, contact name, contact:N selection from a prior match, or a "
                "Messages chat ID from tool_get_chats when group_chat is true. Phone "
                "numbers without a leading + may be misrouted (silently dropped while "
                "the API reports success), so always pass +CCNNN…NNN."
            )
        ),
    ],
    message: Annotated[str, Field(description="Text body to send through Messages.")],
    group_chat: Annotated[
        bool,
        Field(
            description=(
                "Set true only when recipient is a chat ID from tool_get_chats; "
                "false sends to an individual buddy/contact."
            )
        ),
    ] = False,
) -> str:
    """
    Send one outgoing message through the macOS Messages app.

    This has an external side effect: it sends the provided text to the recipient
    using Messages. It may use iMessage or SMS/RCS depending on recipient
    availability and Messages configuration. Requires Automation permission for
    Messages, and the signed-in Mac must be able to send to the recipient. Returns
    a plain-text success or error message; it does not delete or modify existing
    conversations. Use tool_find_contact first when a name is ambiguous, and
    tool_check_imessage_availability when delivery capability is uncertain.
    """
    logger.info(f"Sending message to: {recipient}, group_chat: {group_chat}")
    try:
        # Ensure recipient is a string (handles numbers properly)
        recipient = str(recipient)
        result = send_message(
            recipient=recipient, message=message, group_chat=group_chat
        )
        return result
    except Exception as e:
        logger.error(f"Error in send_message: {str(e)}")
        return f"Error sending message: {str(e)}"


@mcp.tool()
def tool_find_contact(
    ctx: Context,
    name: Annotated[
        str,
        Field(
            description="Contact name or partial name to fuzzy-match in AddressBook."
        ),
    ],
) -> str:
    """
    Find AddressBook contacts by fuzzy name matching.

    This is read-only: it searches local contacts and does not message anyone or
    change contacts. Requires Contacts/AddressBook permission for the host app or
    terminal. Returns a plain-text single match or a numbered list with confidence
    scores; use a returned "contact:N" selector with tool_send_message or
    tool_get_recent_messages. Use tool_check_contacts to inspect available cached
    contacts, and tool_fuzzy_search_messages when searching message text instead.
    """
    logger.info(f"Finding contact: {name}")
    try:
        matches = find_contact_by_name(name)

        if not matches:
            return f"No contacts found matching '{name}'."

        if len(matches) == 1:
            contact = matches[0]
            return f"Found contact: {contact['name']} ({contact['phone']}) with confidence {contact['score']:.2f}"
        else:
            # Format multiple matches
            result = [f"Found {len(matches)} contacts matching '{name}':"]
            for i, contact in enumerate(matches[:10]):  # Limit to top 10
                result.append(
                    f"{i+1}. {contact['name']} ({contact['phone']}) - confidence {contact['score']:.2f}"
                )

            if len(matches) > 10:
                result.append(f"...and {len(matches) - 10} more.")

            return "\n".join(result)
    except Exception as e:
        logger.error(f"Error in find_contact: {str(e)}")
        return f"Error finding contact: {str(e)}"


@mcp.tool()
def tool_check_db_access(ctx: Context) -> str:
    """
    Diagnose read access to the local macOS Messages database.

    This is read-only: it checks whether the server can locate and query the
    Messages SQLite database and returns a plain-text diagnostic report with any
    permission or path errors. It requires Full Disk Access for the host app or
    terminal. Use this after message reads/searches fail or return permission
    errors; use tool_check_addressbook for Contacts/AddressBook access issues.
    """
    logger.info("Checking database access")
    try:
        return check_messages_db_access()
    except Exception as e:
        logger.error(f"Error checking database access: {str(e)}")
        return f"Error checking database access: {str(e)}"


@mcp.tool()
def tool_check_contacts(ctx: Context) -> str:
    """
    List a small sample of contacts available from AddressBook.

    This is read-only: it loads cached local contact names and phone numbers and
    returns a plain-text count plus sample entries. Requires Contacts/AddressBook
    permission. Use this to confirm contact lookup is populated; use
    tool_find_contact to resolve a specific person, and tool_check_addressbook to
    diagnose permission or database access failures.
    """
    logger.info("Checking available contacts")
    try:
        contacts = get_cached_contacts()
        if not contacts:
            return "No contacts found in AddressBook."

        contact_count = len(contacts)
        sample_entries = list(contacts.items())[:10]  # Show first 10 contacts
        formatted_samples = [f"{number} -> {name}" for number, name in sample_entries]

        result = [
            f"Found {contact_count} contacts in AddressBook.",
            "Sample entries (first 10):",
            *formatted_samples,
        ]

        return "\n".join(result)
    except Exception as e:
        logger.error(f"Error checking contacts: {str(e)}")
        return f"Error checking contacts: {str(e)}"


@mcp.tool()
def tool_check_addressbook(ctx: Context) -> str:
    """
    Diagnose read access to the local macOS AddressBook database.

    This is read-only: it checks whether the server can locate and read local
    Contacts/AddressBook data and returns a plain-text diagnostic report with
    permission or path errors. It does not modify contacts. Use this when contact
    lookup fails; use tool_check_db_access when Messages database reads fail.
    """
    logger.info("Checking AddressBook access")
    try:
        return check_addressbook_access()
    except Exception as e:
        logger.error(f"Error checking AddressBook: {str(e)}")
        return f"Error checking AddressBook: {str(e)}"


@mcp.tool()
def tool_get_chats(ctx: Context) -> str:
    """
    List named group chats from the macOS Messages database.

    This is read-only: it queries chat identifiers and display names and does not
    send, edit, or delete messages. Requires Full Disk Access for the host app or
    terminal. Returns a plain-text numbered list of group names and IDs. Use this
    before tool_send_message with group_chat=true; use tool_get_recent_messages
    when you need message contents instead of chat IDs.
    """
    logger.info("Getting available chats")
    try:
        query = "SELECT chat_identifier, display_name FROM chat WHERE display_name IS NOT NULL"
        results = query_messages_db(query)

        if not results:
            return "No group chats found."

        if "error" in results[0]:
            return f"Error accessing chats: {results[0]['error']}"

        # Filter out chats without display names and format the results
        chats = [r for r in results if r.get("display_name")]

        if not chats:
            return "No named group chats found."

        formatted_chats = []
        for i, chat in enumerate(chats, 1):
            formatted_chats.append(
                f"{i}. {chat['display_name']} (ID: {chat['chat_identifier']})"
            )

        return "Available group chats:\n" + "\n".join(formatted_chats)
    except Exception as e:
        logger.error(f"Error getting chats: {str(e)}")
        return f"Error getting chats: {str(e)}"


@mcp.tool()
def tool_check_imessage_availability(
    ctx: Context,
    recipient: Annotated[
        str,
        Field(
            description=(
                "Phone number in E.164 with leading + (e.g. +14155551234) or email "
                "address to check for iMessage capability."
            )
        ),
    ],
) -> str:
    """
    Check whether a recipient appears reachable through iMessage.

    This is a read-only availability check against local Messages services; it
    does not send a message. Requires Messages to be configured on this Mac.
    Returns a plain-text result indicating iMessage availability or likely SMS/RCS
    fallback for phone numbers. Use this before tool_send_message when delivery
    route matters; use tool_find_contact first if you only have a contact name.
    """
    logger.info(f"Checking iMessage availability for: {recipient}")
    try:
        recipient = str(recipient)
        has_imessage = _check_imessage_availability(recipient)

        if has_imessage:
            return f"✅ {recipient} has iMessage available - messages will be sent via iMessage"
        else:
            # Check if it looks like a phone number for SMS fallback
            if any(c.isdigit() for c in recipient):
                return f"📱 {recipient} does not have iMessage - messages will automatically fall back to SMS/RCS"
            else:
                return f"❌ {recipient} does not have iMessage and SMS is not available for email addresses"
    except Exception as e:
        logger.error(f"Error checking iMessage availability: {str(e)}")
        return f"Error checking iMessage availability: {str(e)}"


@mcp.tool()
def tool_fuzzy_search_messages(
    ctx: Context,
    search_term: Annotated[
        str,
        Field(description="Text to fuzzy-match against message bodies."),
    ],
    hours: Annotated[
        int,
        Field(
            description=(
                "Number of hours to search backward. Default 720 (30 days); use 0 "
                "for all available messages. Maximum 87600 (10 years)."
            ),
            ge=0,
            le=87600,
        ),
    ] = 720,
    threshold: Annotated[
        float,
        Field(
            description=(
                "Similarity threshold from 0.0 to 1.0. Default is 0.6; lower "
                "values are more lenient."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = 0.6,
) -> str:
    """
    Fuzzy-search local message text within a time window.

    This is read-only: it queries the local Messages database and does not send,
    edit, or delete messages. Requires Full Disk Access for the host app or
    terminal. Returns a plain-text list of matching messages with similarity
    scores, timestamps, participants, sanitized bodies, and attachment markers
    when present. Use this for approximate text search; use tool_get_recent_messages
    for unfiltered chronological context and tool_find_contact for contact lookup.
    """
    if not (0.0 <= threshold <= 1.0):
        return "Error: Threshold must be between 0.0 and 1.0."
    if hours < 0:
        return "Error: Hours cannot be negative."

    logger.info(
        f"Tool: Fuzzy searching messages for '{search_term}' in last {hours} hours with threshold {threshold}"
    )
    try:
        result = fuzzy_search_messages(
            search_term=search_term, hours=hours, threshold=threshold
        )
        return result
    except Exception as e:
        logger.error(f"Error in tool_fuzzy_search_messages: {e}", exc_info=True)
        return f"An unexpected error occurred during fuzzy message search: {str(e)}"


@mcp.tool()
def tool_search_attachments(
    ctx: Context,
    start_date: Annotated[
        str | None,
        Field(description='Optional inclusive start date in "YYYY-MM-DD" format.'),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description='Optional inclusive end date in "YYYY-MM-DD" format.'),
    ] = None,
    contact: Annotated[
        str | None,
        Field(
            description=(
                "Optional contact filter: contact name, phone number in E.164 with "
                "leading + (e.g. +14155551234), or email address."
            )
        ),
    ] = None,
    mime_type: Annotated[
        str | None,
        Field(
            description='Optional MIME type or prefix filter, such as "image/" or "application/pdf".'
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="Maximum number of attachment metadata rows to return.", ge=1
        ),
    ] = 50,
) -> str:
    """
    Search message attachments by date range, contact, and MIME type.

    This is read-only and returns metadata only; it does not return file bytes or
    modify attachments. Requires Full Disk Access for the host app or terminal.
    Results include attachment IDs, MIME types, filenames, sizes, timestamps, and
    senders. Use this to find candidate files cheaply, then call
    tool_get_attachment for one specific attachment. Use tool_fuzzy_search_messages
    when searching message text instead of attachment metadata.
    """
    logger.info(
        f"Searching attachments: start={start_date} end={end_date} "
        f"contact={contact} mime={mime_type} limit={limit}"
    )
    try:
        if contact is not None:
            contact = str(contact)
        return search_attachments(
            start_date=start_date,
            end_date=end_date,
            contact=contact,
            mime_type=mime_type,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Error in tool_search_attachments: {e}", exc_info=True)
        return f"Error searching attachments: {str(e)}"


@mcp.tool()
def tool_get_attachment(
    ctx: Context,
    attachment_id: Annotated[
        int,
        Field(
            description=(
                "Messages attachment ROWID from tool_search_attachments or an "
                "attachment marker in message search results."
            ),
            ge=1,
        ),
    ],
    max_bytes: Annotated[
        int,
        Field(
            description=(
                "Maximum inline image payload size in bytes. Larger files return "
                "a local filesystem path instead."
            ),
            ge=1,
        ),
    ] = 5_000_000,
) -> object:
    """
    Fetch a specific attachment by its database ROWID.

    This is read-only: it resolves a local Messages attachment file and does not
    modify or delete it. Requires Full Disk Access for the host app or terminal.
    For image MIME types under max_bytes, returns the image inline so you can see
    it directly. For PDFs, video, audio, missing files, or oversize images,
    returns a plain-text filesystem path or error. Use tool_search_attachments
    first unless you already have an attachment ID.
    """
    logger.info(f"Getting attachment id={attachment_id} max_bytes={max_bytes}")
    try:
        return get_attachment(attachment_id=int(attachment_id), max_bytes=max_bytes)
    except Exception as e:
        logger.error(f"Error in tool_get_attachment: {e}", exc_info=True)
        return f"Error getting attachment: {str(e)}"


@mcp.resource("messages://recent/{hours}")
def get_recent_messages_resource(hours: int = 24) -> str:
    """Resource that provides recent messages."""
    return get_recent_messages(hours=hours)


@mcp.resource("messages://contact/{contact}/{hours}")
def get_contact_messages_resource(contact: str, hours: int = 24) -> str:
    """Resource that provides messages from a specific contact."""
    return get_recent_messages(hours=hours, contact=contact)


def run_server() -> None:
    """Run the MCP server with proper error handling"""
    try:
        logger.info("Starting Mac Messages MCP server...")
        mcp.run()
    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    run_server()
