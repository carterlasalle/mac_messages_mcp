"""
Core functionality for interacting with macOS Messages app
"""
import os
import sqlite3
import subprocess
import json
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

def normalize_phone_number(phone: str) -> str:
    """
    Normalize a phone number by removing all non-digit characters.
    """
    if not phone:
        return ""
    return ''.join(c for c in phone if c.isdigit())

# Global cache for contacts map
_CONTACTS_CACHE = None
_LAST_CACHE_UPDATE = 0
_CACHE_TTL = 300  # 5 minutes in seconds

def get_addressbook_contacts() -> Dict[str, str]:
    """
    Query the macOS AddressBook database to get contacts and their phone numbers.
    Returns a dictionary mapping normalized phone numbers to contact names.
    """
    contacts_map = {}
    
    try:
        # Form the SQL query to execute via command line
        cmd = """
        sqlite3 ~/Library/"Application Support"/AddressBook/Sources/*/AddressBook-v22.abcddb<<EOF
        .mode json
        SELECT DISTINCT
            ZABCDRECORD.ZFIRSTNAME [FIRST NAME],
            ZABCDRECORD.ZLASTNAME [LAST NAME],
            ZABCDPHONENUMBER.ZFULLNUMBER [FULL NUMBER]
        FROM
            ZABCDRECORD
            LEFT JOIN ZABCDPHONENUMBER ON ZABCDRECORD.Z_PK = ZABCDPHONENUMBER.ZOWNER
        ORDER BY
            ZABCDRECORD.ZLASTNAME,
            ZABCDRECORD.ZFIRSTNAME,
            ZABCDPHONENUMBER.ZORDERINGINDEX ASC;
        EOF
        """
        
        # Execute the command
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            # Parse the JSON output line by line (it's a series of JSON objects)
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                
                # Remove trailing commas that might cause JSON parsing errors
                line = line.rstrip(',')
                
                try:
                    contact = json.loads(line)
                    first_name = contact.get("FIRST NAME", "")
                    last_name = contact.get("LAST NAME", "")
                    phone = contact.get("FULL NUMBER", "")
                    
                    # Skip entries without phone numbers
                    if not phone:
                        continue
                    
                    # Clean up phone number and remove any image metadata
                    if "X-IMAGETYPE" in phone:
                        phone = phone.split("X-IMAGETYPE")[0]
                    
                    # Create full name
                    full_name = " ".join(filter(None, [first_name, last_name]))
                    if not full_name.strip():
                        continue
                    
                    # Normalize phone number and add to map
                    normalized_phone = normalize_phone_number(phone)
                    if normalized_phone:
                        contacts_map[normalized_phone] = full_name
                except json.JSONDecodeError:
                    # Skip individual lines that fail to parse
                    continue
    
    except Exception as e:
        print(f"Error getting AddressBook contacts: {str(e)}")
    
    return contacts_map

def get_cached_contacts() -> Dict[str, str]:
    """Get cached contacts map or refresh if needed"""
    global _CONTACTS_CACHE, _LAST_CACHE_UPDATE
    
    current_time = time.time()
    if _CONTACTS_CACHE is None or (current_time - _LAST_CACHE_UPDATE) > _CACHE_TTL:
        _CONTACTS_CACHE = get_addressbook_contacts()
        _LAST_CACHE_UPDATE = current_time
    
    return _CONTACTS_CACHE

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
        
        # Check if the database file exists and is accessible
        if not os.path.exists(db_path):
            return [{"error": f"Messages database not found at {db_path}"}]
            
        # Try to connect to the database
        try:
            conn = sqlite3.connect(db_path)
        except sqlite3.OperationalError as e:
            return [{"error": f"Cannot access Messages database. Please grant Full Disk Access permission to your terminal application in System Preferences > Security & Privacy > Privacy > Full Disk Access. Error: {str(e)}"}]
            
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    except Exception as e:
        return [{"error": str(e)}]

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
    normalized_handle = normalize_phone_number(handle_id_value)
    
    # Try different variations of the number for matching
    if normalized_handle in contacts:
        return contacts[normalized_handle]
    
    # Sometimes numbers in the addressbook have the country code, but messages don't
    if normalized_handle.startswith('1') and len(normalized_handle) > 10:
        # Try without country code
        if normalized_handle[1:] in contacts:
            return contacts[normalized_handle[1:]]
    elif len(normalized_handle) == 10:  # US number without country code
        # Try with country code
        if '1' + normalized_handle in contacts:
            return contacts['1' + normalized_handle]
    
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
    
    if contacts and len(contacts) > 0 and "display_name" in contacts[0] and contacts[0]["display_name"]:
        return contacts[0]["display_name"]
    
    # If no contact name found, return the phone number or email
    return handle_id_value

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
    
    # Make sure we're using a string representation for the timestamp
    # to avoid integer overflow issues when binding to SQLite
    timestamp_str = str(seconds_since_apple_epoch)
    
    # Build the SQL query - use string comparison instead of numeric
    query = """
    SELECT 
        m.date, 
        m.text, 
        m.is_from_me,
        m.handle_id
    FROM 
        message m
    WHERE 
        CAST(m.date AS TEXT) > ? 
    """
    
    params = (timestamp_str,)
    
    # Add contact filter if provided
    if contact:
        query += "AND m.handle_id IN (SELECT ROWID FROM handle WHERE id = ?) "
        params = (timestamp_str, contact)
    
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
        # Convert Apple timestamp to readable date - handle as string first
        try:
            # First convert to integer safely
            msg_date_int = int(str(msg["date"]))
            msg_date = apple_epoch + timedelta(seconds=msg_date_int)
        except (ValueError, TypeError, OverflowError):
            # If conversion fails, use a placeholder
            msg_date = datetime.now()
            
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
    
def check_messages_db_access() -> str:
    """Check if the Messages database is accessible and return detailed information."""
    try:
        db_path = get_messages_db_path()
        status = []
        
        # Check if the file exists
        if not os.path.exists(db_path):
            return f"ERROR: Messages database not found at {db_path}"
        
        status.append(f"Database file exists at: {db_path}")
        
        # Check file permissions
        try:
            with open(db_path, 'rb') as f:
                # Just try to read a byte to confirm access
                f.read(1)
            status.append("File is readable")
        except PermissionError:
            return f"ERROR: Permission denied when trying to read {db_path}. Please grant Full Disk Access permission to your terminal application."
        except Exception as e:
            return f"ERROR: Unknown error reading file: {str(e)}"
        
        # Try to connect to the database
        try:
            conn = sqlite3.connect(db_path)
            status.append("Successfully connected to database")
            
            # Test a simple query
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM sqlite_master")
            count = cursor.fetchone()[0]
            status.append(f"Database contains {count} tables")
            
            # Check if the necessary tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('message', 'handle', 'chat')")
            tables = [row[0] for row in cursor.fetchall()]
            if 'message' in tables and 'handle' in tables:
                status.append("Required tables (message, handle) are present")
            else:
                status.append(f"WARNING: Some required tables are missing. Found: {', '.join(tables)}")
            
            conn.close()
        except sqlite3.OperationalError as e:
            return f"ERROR: Database connection error: {str(e)}"
        
        return "\n".join(status)
    except Exception as e:
        return f"ERROR: Unexpected error during database access check: {str(e)}"