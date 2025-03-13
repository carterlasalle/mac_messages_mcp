"""
MCP server implementation for Mac Messages
"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context

from .messages import get_recent_messages, send_message

# Initialize the MCP server
mcp = FastMCP("MessageBridge")

@mcp.tool()
def tool_get_recent_messages(hours: int = 24, contact: Optional[str] = None) -> str:
    """
    Get recent messages from the Messages app.
    
    Args:
        hours: Number of hours to look back (default: 24)
        contact: Filter by contact phone number or email (optional)
    
    Returns:
        Formatted string with recent messages
    """
    return get_recent_messages(hours=hours, contact=contact)

@mcp.tool()
def tool_send_message(recipient: str, message: str) -> str:
    """
    Send a message using the Messages app.
    
    Args:
        recipient: Phone number, email, or contact name
        message: Message text to send
    
    Returns:
        Success or error message
    """
    return send_message(recipient=recipient, message=message)

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

def run_server():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    run_server() 