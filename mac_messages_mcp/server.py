#!/usr/bin/env python3
"""
Mac Messages MCP - Entry point fixed for proper MCP protocol implementation
"""

import asyncio
import logging
import sys

from mcp.server.fastmcp import Context, FastMCP

from mac_messages_mcp.messages import (
    _check_imessage_availability,
    check_addressbook_access,
    check_messages_db_access,
    find_contact_by_name,
    fuzzy_search_messages,
    get_cached_contacts,
    get_recent_messages,
    query_messages_db,
    send_message,
)

# Configure logging to stderr for debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

logger = logging.getLogger("mac_messages_mcp")

# Initialize the MCP server with proper description
mcp = FastMCP(
    "MessageBridge", 
    description="A bridge for interacting with macOS Messages app"
)

@mcp.tool()
def tool_get_recent_messages(ctx: Context, hours: int = 24, contact: str = None) -> str:
    """
    Get recent messages from the Messages app.
    
    Args:
        hours: Number of hours to look back (default: 24)
        contact: Filter by contact name, phone number, or email (optional)
                Use "contact:N" to select a specific contact from previous matches
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
def tool_send_message(ctx: Context, recipient: str, message: str, group_chat: bool = False) -> str:
    """
    Send a message using the Messages app.
    
    Args:
        recipient: Phone number, email, contact name, or "contact:N" to select from matches
                  For example, "contact:1" selects the first contact from a previous search
        message: Message text to send
        group_chat: Whether to send to a group chat (uses chat ID instead of buddy)
    """
    logger.info(f"Sending message to: {recipient}, group_chat: {group_chat}")
    try:
        # Ensure recipient is a string (handles numbers properly)
        recipient = str(recipient)
        result = send_message(recipient=recipient, message=message, group_chat=group_chat)
        return result
    except Exception as e:
        logger.error(f"Error in send_message: {str(e)}")
        return f"Error sending message: {str(e)}"

@mcp.tool()
def tool_find_contact(ctx: Context, name: str) -> str:
    """
    Find a contact by name using fuzzy matching.
    
    Args:
        name: The name to search for
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
                result.append(f"{i+1}. {contact['name']} ({contact['phone']}) - confidence {contact['score']:.2f}")
            
            if len(matches) > 10:
                result.append(f"...and {len(matches) - 10} more.")
            
            return "\n".join(result)
    except Exception as e:
        logger.error(f"Error in find_contact: {str(e)}")
        return f"Error finding contact: {str(e)}"

@mcp.tool()
def tool_check_db_access(ctx: Context) -> str:
    """
    Diagnose database access issues.
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
    List available contacts in the address book.
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
            *formatted_samples
        ]
        
        return "\n".join(result)
    except Exception as e:
        logger.error(f"Error checking contacts: {str(e)}")
        return f"Error checking contacts: {str(e)}"

@mcp.tool()
def tool_check_addressbook(ctx: Context) -> str:
    """
    Diagnose AddressBook access issues.
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
    List available group chats from the Messages app.
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
        chats = [r for r in results if r.get('display_name')]
        
        if not chats:
            return "No named group chats found."
        
        formatted_chats = []
        for i, chat in enumerate(chats, 1):
            formatted_chats.append(f"{i}. {chat['display_name']} (ID: {chat['chat_identifier']})")
        
        return "Available group chats:\n" + "\n".join(formatted_chats)
    except Exception as e:
        logger.error(f"Error getting chats: {str(e)}")
        return f"Error getting chats: {str(e)}"


@mcp.tool()
def tool_check_imessage_availability(ctx: Context, recipient: str) -> str:
    """
    Check if a recipient has iMessage available.
    
    This tool helps determine whether to send via iMessage or SMS/RCS.
    Useful for debugging delivery issues or choosing the right service.
    
    Args:
        recipient: Phone number or email to check for iMessage availability
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
    ctx: Context, search_term: str, hours: int = 24, threshold: float = 0.6
) -> str:
    """
    Fuzzy search for messages containing the search_term within the last N hours.
    Returns messages that match the search term with a similarity score.

    Args:
        search_term: The text to search for in messages.
        hours: How many hours back to search (default 24). Must be positive.
        threshold: Similarity threshold for matching (0.0 to 1.0, default 0.6). Lower is more lenient.
    """
    if not (0.0 <= threshold <= 1.0):
        return "Error: Threshold must be between 0.0 and 1.0."
    if hours <= 0:
        return "Error: Hours must be a positive integer."

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


@mcp.resource("messages://recent/{hours}")
def get_recent_messages_resource(hours: int = 24) -> str:
    """Resource that provides recent messages."""
    return get_recent_messages(hours=hours)

@mcp.resource("messages://contact/{contact}/{hours}")
def get_contact_messages_resource(contact: str, hours: int = 24) -> str:
    """Resource that provides messages from a specific contact."""
    return get_recent_messages(hours=hours, contact=contact)

def run_server():
    """Run the MCP server with proper error handling"""
    try:
        logger.info("Starting Mac Messages MCP server...")
        mcp.run()
    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    run_server()