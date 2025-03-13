"""
MCP server implementation for Mac Messages with improved contact handling
"""
import json
from typing import Optional, List, Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from .messages import get_recent_messages, send_message, find_contact_by_name

# Initialize the MCP server
mcp = FastMCP("MessageBridge")

@mcp.tool()
def tool_get_recent_messages(hours: int = 24, contact: Optional[str] = None) -> str:
    """
    Get recent messages from the Messages app.
    
    Args:
        hours: Number of hours to look back (default: 24)
        contact: Filter by contact name, phone number, or email (optional)
                Use "contact:N" to select a specific contact from previous matches
    
    Returns:
        Formatted string with recent messages
    """
    # Convert contact to string if provided (handles numeric phone numbers)
    if contact is not None:
        contact = str(contact)
    
    return get_recent_messages(hours=hours, contact=contact)

@mcp.tool()
def tool_send_message(recipient: str, message: str) -> str:
    """
    Send a message using the Messages app.
    
    Args:
        recipient: Phone number, email, contact name, or "contact:N" to select from matches
                  For example, "contact:1" selects the first contact from a previous search
        message: Message text to send
    
    Returns:
        Success or error message
    """
    # Ensure recipient is a string (handles numbers properly)
    recipient = str(recipient)
    return send_message(recipient=recipient, message=message)

@mcp.tool()
def tool_find_contact(name: str) -> str:
    """
    Find a contact by name using fuzzy matching.
    
    Args:
        name: The name to search for
    
    Returns:
        Information about matching contacts
    """
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

@mcp.resource("messages://recent/{hours}")
def get_recent_messages_resource(hours: int = 24) -> str:
    """Resource that provides recent messages."""
    return get_recent_messages(hours=hours)

@mcp.resource("messages://contact/{contact}/{hours}")
def get_contact_messages_resource(contact: str, hours: int = 24) -> str:
    """Resource that provides messages from a specific contact."""
    return get_recent_messages(hours=hours, contact=contact)

@mcp.tool()
def tool_check_db_access() -> str:
    """
    Diagnose database access issues.
    
    Returns:
        Detailed information about database access status
    """
    from .messages import check_messages_db_access
    return check_messages_db_access()

@mcp.tool()
def tool_check_contacts() -> str:
    """
    List available contacts in the address book.
    
    Returns:
        Information about the available contacts
    """
    from .messages import get_cached_contacts
    
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

@mcp.tool()
def tool_check_addressbook() -> str:
    """
    Diagnose AddressBook access issues.
    
    Returns:
        Detailed information about AddressBook access status
    """
    from .messages import check_addressbook_access
    return check_addressbook_access()

def run_server():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    run_server()