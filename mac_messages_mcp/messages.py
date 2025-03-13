"""
Core functionality for interacting with macOS Messages app
"""
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

def run_applescript(script: str) -> str:
    """Run an AppleScript and return the result."""
    proc = subprocess.Popen(['osascript', '-e', script], 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE)
    out, err = proc.communicate()
    if proc.returncode != 0:
        return f"Error: {err.decode('utf-8')}"
    return out.decode('utf-8').strip()

def get_messages_db_path() -> str:
    """Get the path to the Messages database."""
    home_dir = os.path.expanduser("~")
    return os.path.join(home_dir, "Library/Messages/chat.db")

def query_messages_db(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Query the Messages database and return results as a list of dictionaries."""
    try:
        db_path = get_messages_db_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    except Exception as e:
        return [{"error": str(e)}]

def get_contact_name(handle_id: int) -> str:
    """Get contact name from handle_id."""
    query = """
    SELECT id FROM handle WHERE ROWID = ?
    """
    results = query_messages_db(query, (handle_id,))
    if results and "id" in results[0]:
        return results[0]["id"]
    return "Unknown"

def get_recent_messages(hours: int = 24, contact: Optional[str] = None) -> str:
    """
    Get recent messages from the Messages app.
    
    Args:
        hours: Number of hours to look back (default: 24)
        contact: Filter by contact phone number or email (optional)
    
    Returns:
        Formatted string with recent messages
    """
    # Calculate the timestamp for X hours ago
    current_time = datetime.now()
    hours_ago = current_time - timedelta(hours=hours)
    
    # Convert to Apple's timestamp format (seconds since 2001-01-01)
    apple_epoch = datetime(2001, 1, 1)
    seconds_since_apple_epoch = int((hours_ago - apple_epoch).total_seconds())
    
    # Build the SQL query
    query = """
    SELECT 
        m.date, 
        m.text, 
        m.is_from_me,
        m.handle_id
    FROM 
        message m
    WHERE 
        m.date > ? 
    """
    
    params = (seconds_since_apple_epoch,)
    
    # Add contact filter if provided
    if contact:
        query += "AND m.handle_id IN (SELECT ROWID FROM handle WHERE id = ?) "
        params = (seconds_since_apple_epoch, contact)
    
    query += "ORDER BY m.date DESC LIMIT 100"
    
    # Execute the query
    messages = query_messages_db(query, params)
    
    # Format the results
    if not messages:
        return "No messages found in the specified time period."
    
    if "error" in messages[0]:
        return f"Error accessing messages: {messages[0]['error']}"
    
    formatted_messages = []
    for msg in messages:
        # Convert Apple timestamp to readable date
        msg_date = apple_epoch + timedelta(seconds=msg["date"])
        direction = "You" if msg["is_from_me"] else get_contact_name(msg["handle_id"])
        
        formatted_messages.append(
            f"[{msg_date.strftime('%Y-%m-%d %H:%M:%S')}] {direction}: {msg['text']}"
        )
    
    return "\n".join(formatted_messages)

def send_message(recipient: str, message: str) -> str:
    """
    Send a message using the Messages app.
    
    Args:
        recipient: Phone number, email, or contact name
        message: Message text to send
    
    Returns:
        Success or error message
    """
    # Clean the inputs for AppleScript
    safe_message = message.replace('"', '\\"')
    safe_recipient = recipient.replace('"', '\\"')
    
    # AppleScript to send a message
    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{safe_recipient}" of targetService
        send "{safe_message}" to targetBuddy
    end tell
    '''
    
    try:
        result = run_applescript(script)
        if result.startswith("Error"):
            return result
        return f"Message sent successfully to {recipient}"
    except Exception as e:
        return f"Error sending message: {str(e)}" 