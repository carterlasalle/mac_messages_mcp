"""
Core functionality for interacting with macOS Messages app
"""
import difflib
import glob
import json
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from thefuzz import fuzz


def run_applescript(script: str) -> str:
    """Run an AppleScript and return the result."""
    proc = subprocess.Popen(['osascript', '-e', script], 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE)
    out, err = proc.communicate()
    if proc.returncode != 0:
        return f"Error: {err.decode('utf-8')}"
    return out.decode('utf-8').strip()

def get_chat_mapping() -> Dict[str, str]:
    """
    Get mapping from room_name to display_name in chat table
    """
    conn = sqlite3.connect(get_messages_db_path())
    cursor = conn.cursor()

    cursor.execute("SELECT room_name, display_name FROM chat")
    result_set = cursor.fetchall()

    mapping = {room_name: display_name for room_name, display_name in result_set}

    conn.close()

    return mapping

def extract_body_from_attributed(attributed_body):
    """
    Extract message content from attributedBody binary data
    """
    if attributed_body is None:
        return None
        
    try:
        # Try to decode attributedBody 
        decoded = attributed_body.decode('utf-8', errors='replace')
        
        # Extract content using pattern matching
        if "NSNumber" in decoded:
            decoded = decoded.split("NSNumber")[0]
            if "NSString" in decoded:
                decoded = decoded.split("NSString")[1]
                if "NSDictionary" in decoded:
                    decoded = decoded.split("NSDictionary")[0]
                    decoded = decoded[6:-12]
                    return decoded
    except Exception as e:
        print(f"Error extracting from attributedBody: {e}")
    
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
            conn = sqlite3.connect(db_path)
        except sqlite3.OperationalError as e:
            return [{"error": f"Cannot access Messages database. Please grant Full Disk Access permission to your terminal application in System Preferences > Security & Privacy > Privacy > Full Disk Access. Error: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."}]
            
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
    if not phone:
        return ""
    return ''.join(c for c in phone if c.isdigit())

# Global cache for contacts map
_CONTACTS_CACHE = None
_LAST_CACHE_UPDATE = 0
_CACHE_TTL = 300  # 5 minutes in seconds

def clean_name(name: str) -> str:
    """
    Clean a name by removing emojis and extra whitespace.
    """
    # Remove emoji and other non-alphanumeric characters except spaces, hyphens, and apostrophes
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F700-\U0001F77F"  # alchemical symbols
        "\U0001F780-\U0001F7FF"  # Geometric Shapes
        "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FA00-\U0001FA6F"  # Chess Symbols
        "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "\U00002702-\U000027B0"  # Dingbats
        "\U000024C2-\U0001F251" 
        "]+"
    )
    
    name = emoji_pattern.sub(r'', name)
    
    # Keep alphanumeric, spaces, apostrophes, and hyphens
    name = re.sub(r'[^\w\s\'\-]', '', name, flags=re.UNICODE)
    
    # Remove extra whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name

def fuzzy_match(query: str, candidates: List[Tuple[str, Any]], threshold: float = 0.6) -> List[Tuple[str, Any, float]]:
    """
    Find fuzzy matches between query and a list of candidates.
    
    Args:
        query: The search string
        candidates: List of (name, value) tuples to search through
        threshold: Minimum similarity score (0-1) to consider a match
        
    Returns:
        List of (name, value, score) tuples for matches, sorted by score
    """
    query = clean_name(query).lower()
    results = []
    
    for name, value in candidates:
        clean_candidate = clean_name(name).lower()
        
        # Try exact match first (case insensitive)
        if query == clean_candidate:
            results.append((name, value, 1.0))
            continue
            
        # Check if query is a substring of the candidate
        if query in clean_candidate:
            # Longer substring matches get higher scores
            score = len(query) / len(clean_candidate) * 0.9  # max 0.9 for substring
            if score >= threshold:
                results.append((name, value, score))
                continue
                
        # Otherwise use difflib for fuzzy matching
        score = difflib.SequenceMatcher(None, query, clean_candidate).ratio()
        if score >= threshold:
            results.append((name, value, score))
    
    # Sort results by score (highest first)
    return sorted(results, key=lambda x: x[2], reverse=True)

def query_addressbook_db(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Query the AddressBook database and return results as a list of dictionaries."""
    try:
        # Find the AddressBook database paths
        home_dir = os.path.expanduser("~")
        sources_path = os.path.join(home_dir, "Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb")
        db_paths = glob.glob(sources_path)
        
        if not db_paths:
            return [{"error": f"AddressBook database not found at {sources_path} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."}]
        
        # Try each database path until one works
        all_results = []
        for db_path in db_paths:
            try:
                conn = sqlite3.connect(db_path)
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
            return [{"error": f"Could not access any AddressBook databases. Please grant Full Disk Access permission. PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."}]
            
        return all_results
    except Exception as e:
        return [{"error": str(e)}]

def get_addressbook_contacts() -> Dict[str, str]:
    """
    Query the macOS AddressBook database to get contacts and their phone numbers.
    Returns a dictionary mapping normalized phone numbers to contact names.
    """
    contacts_map = {}
    
    # Define the query to get contact names and phone numbers
    query = """
    SELECT 
        ZABCDRECORD.ZFIRSTNAME as first_name,
        ZABCDRECORD.ZLASTNAME as last_name,
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
    
    try:
        # For testing/fallback, parse the user-provided examples in cases where direct DB access fails
        # This is a temporary workaround until full disk access is granted
        if 'USE_TEST_DATA' in os.environ and os.environ['USE_TEST_DATA'].lower() == 'true':
            contacts = [
                {"first_name":"TEST", "last_name":"TEST", "phone":"+11111111111"}
            ]
            return process_contacts(contacts)
        
        # Try to query database directly
        results = query_addressbook_db(query)
        
        if results and "error" in results[0]:
            print(f"Error getting AddressBook contacts: {results[0]['error']}")
            # Fall back to subprocess method if direct DB access fails
            return get_addressbook_contacts_subprocess()
        
        return process_contacts(results)
    except Exception as e:
        print(f"Error getting AddressBook contacts: {str(e)}")
        return {}

def process_contacts(contacts) -> Dict[str, str]:
    """Process contact records into a normalized phone -> name map"""
    contacts_map = {}
    name_to_numbers = {}  # For reverse lookup
    
    for contact in contacts:
        try:
            first_name = contact.get("first_name", "")
            last_name = contact.get("last_name", "")
            phone = contact.get("phone", "")
            
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
                
                # Add to reverse lookup
                if full_name not in name_to_numbers:
                    name_to_numbers[full_name] = []
                name_to_numbers[full_name].append(normalized_phone)
        except Exception as e:
            # Skip individual entries that fail to process
            print(f"Error processing contact: {str(e)}")
            continue
    
    # Store the reverse lookup in a global variable for later use
    global _NAME_TO_NUMBERS_MAP
    _NAME_TO_NUMBERS_MAP = name_to_numbers
    
    return contacts_map

def get_addressbook_contacts_subprocess() -> Dict[str, str]:
    """
    Legacy method to get contacts using subprocess.
    Only used as fallback when direct database access fails.
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
                    
                    # Process contact as in the main method
                    if not phone:
                        continue
                        
                    if "X-IMAGETYPE" in phone:
                        phone = phone.split("X-IMAGETYPE")[0]
                    
                    full_name = " ".join(filter(None, [first_name, last_name]))
                    if not full_name.strip():
                        continue
                    
                    normalized_phone = normalize_phone_number(phone)
                    if normalized_phone:
                        contacts_map[normalized_phone] = full_name
                except json.JSONDecodeError:
                    # Skip individual lines that fail to parse
                    continue
    except Exception as e:
        print(f"Error getting AddressBook contacts via subprocess: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE.")
    
    return contacts_map

# Global variable for reverse contact lookup
_NAME_TO_NUMBERS_MAP = {}

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
    Find contacts by name using fuzzy matching.
    
    Args:
        name: The name to search for
    
    Returns:
        List of matching contacts (may be multiple if ambiguous)
    """
    contacts = get_cached_contacts()
    
    # Build a list of (name, phone) pairs to search through
    candidates = [(contact_name, phone) for phone, contact_name in contacts.items()]
    
    # Perform fuzzy matching
    matches = fuzzy_match(name, candidates)
    
    # Convert to a list of contact dictionaries
    results = []
    for contact_name, phone, score in matches:
        results.append({
            "name": contact_name,
            "phone": phone,
            "score": score
        })
    
    return results

def send_message(recipient: str, message: str, group_chat: bool = False) -> str:
    """
    Send a message using the Messages app with improved contact resolution.
    
    Args:
        recipient: Phone number, email, contact name, or special format for contact selection
                  Use "contact:N" to select the Nth contact from a previous ambiguous match
        message: Message text to send
        group_chat: Whether this is a group chat (uses chat ID instead of buddy)
    
    Returns:
        Success or error message
    """
    # Convert to string to ensure phone numbers work properly
    recipient = str(recipient).strip()
    
    # Handle contact selection format (contact:N)
    if recipient.lower().startswith("contact:"):
        try:
            # Get the selected index (1-based)
            index = int(recipient.split(":", 1)[1].strip()) - 1
            
            # Get the most recent contact matches from global cache
            if not hasattr(send_message, "recent_matches") or not send_message.recent_matches:
                return "No recent contact matches available. Please search for a contact first."
            
            if index < 0 or index >= len(send_message.recent_matches):
                return f"Invalid selection. Please choose a number between 1 and {len(send_message.recent_matches)}."
            
            # Get the selected contact
            contact = send_message.recent_matches[index]
            return _send_message_to_recipient(contact['phone'], message, contact['name'], group_chat)
        except (ValueError, IndexError) as e:
            return f"Error selecting contact: {str(e)}"
    
    # Check if recipient is directly a phone number
    if all(c.isdigit() or c in '+- ()' for c in recipient):
        # Clean the phone number
        clean_number = ''.join(c for c in recipient if c.isdigit())
        return _send_message_to_recipient(clean_number, message, group_chat=group_chat)
    
    # Try to find the contact by name
    contacts = find_contact_by_name(recipient)
    
    if not contacts:
        return f"Error: Could not find any contact matching '{recipient}'"
    
    if len(contacts) == 1:
        # Single match, use it
        contact = contacts[0]
        return _send_message_to_recipient(contact['phone'], message, contact['name'], group_chat)
    else:
        # Store the matches for later selection
        send_message.recent_matches = contacts
        
        # Multiple matches, return them all
        contact_list = "\n".join([f"{i+1}. {c['name']} ({c['phone']})" for i, c in enumerate(contacts[:10])])
        return f"Multiple contacts found matching '{recipient}'. Please specify which one using 'contact:N' where N is the number:\n{contact_list}"

# Initialize the static variable for recent matches
send_message.recent_matches = []

def _send_message_to_recipient(recipient: str, message: str, contact_name: str = None, group_chat: bool = False) -> str:
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
    try:
        # Create a temporary file with the message content
        file_path = os.path.abspath('imessage_tmp.txt')
        
        with open(file_path, 'w') as f:
            f.write(message)
        
        # Adjust the AppleScript command based on whether this is a group chat
        if not group_chat:
            command = f'tell application "Messages" to send (read (POSIX file "{file_path}") as «class utf8») to buddy "{recipient}"'
        else:
            command = f'tell application "Messages" to send (read (POSIX file "{file_path}") as «class utf8») to chat "{recipient}"'
        
        # Run the AppleScript
        result = run_applescript(command)
        
        # Clean up the temporary file
        try:
            os.remove(file_path)
        except:
            pass
        
        # Check result
        if result.startswith("Error:"):
            # Try fallback to direct method
            return _send_message_direct(recipient, message, contact_name, group_chat)
        
        # Message sent successfully
        display_name = contact_name if contact_name else recipient
        return f"Message sent successfully to {display_name}"
    except Exception as e:
        # Try fallback method
        return _send_message_direct(recipient, message, contact_name, group_chat)

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
    Get recent messages from the Messages app using attributedBody for content.
    
    Args:
        hours: Number of hours to look back (default: 24)
        contact: Filter by contact name, phone number, or email (optional)
                Use "contact:N" to select a specific contact from previous matches
    
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
    
    handle_id = None
    
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
                if not hasattr(get_recent_messages, "recent_matches") or not get_recent_messages.recent_matches:
                    return "No recent contact matches available. Please search for a contact first."
                
                if index >= len(get_recent_messages.recent_matches):
                    return f"Invalid selection. Please choose a number between 1 and {len(get_recent_messages.recent_matches)}."
                
                # Get the selected contact's phone number
                contact = get_recent_messages.recent_matches[index]['phone']
            except Exception as e:
                return f"Error processing contact selection: {str(e)}"
        
        # Check if contact might be a name rather than a phone number or email
        if not all(c.isdigit() or c in '+- ()@.' for c in contact):
            # Try fuzzy matching
            matches = find_contact_by_name(contact)
            
            if not matches:
                return f"No contacts found matching '{contact}'."
            
            if len(matches) == 1:
                # Single match, use its phone number
                contact = matches[0]['phone']
            else:
                # Store the matches for later selection
                get_recent_messages.recent_matches = matches
                
                # Multiple matches, return them all
                contact_list = "\n".join([f"{i+1}. {c['name']} ({c['phone']})" for i, c in enumerate(matches[:10])])
                return f"Multiple contacts found matching '{contact}'. Please specify which one using 'contact:N' where N is the number:\n{contact_list}"
        
        # At this point, contact should be a phone number or email
        # Try to find handle_id with improved phone number matching
        if '@' in contact:
            # This is an email
            query = "SELECT ROWID FROM handle WHERE id = ?"
            results = query_messages_db(query, (contact,))
            if results and not "error" in results[0] and len(results) > 0:
                handle_id = results[0]["ROWID"]
        else:
            # This is a phone number - try various formats
            handle_id = find_handle_by_phone(contact)
            
        if not handle_id:
            # Try a direct search in message table to see if any messages exist
            normalized = normalize_phone_number(contact)
            query = """
            SELECT COUNT(*) as count 
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE h.id LIKE ?
            """
            results = query_messages_db(query, (f"%{normalized}%",))
            
            if results and not "error" in results[0] and results[0].get("count", 0) == 0:
                # No messages found but the query was valid
                return f"No message history found with '{contact}'."
            else:
                # Could not find the handle at all
                return f"Could not find any messages with contact '{contact}'. Verify the phone number or email is correct."
    
    # Calculate the timestamp for X hours ago
    current_time = datetime.now(timezone.utc)
    hours_ago = current_time - timedelta(hours=hours)
    
    # Convert to Apple's timestamp format (nanoseconds since 2001-01-01)
    # Apple's Core Data uses nanoseconds, not seconds
    apple_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
    seconds_since_apple_epoch = (hours_ago - apple_epoch).total_seconds()
    
    # Convert to nanoseconds (Apple's format)
    nanoseconds_since_apple_epoch = int(seconds_since_apple_epoch * 1_000_000_000)
    
    # Make sure we're using a string representation for the timestamp
    # to avoid integer overflow issues when binding to SQLite
    timestamp_str = str(nanoseconds_since_apple_epoch)
    
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
    
    params = (timestamp_str,)
    
    # Add contact filter if handle_id was found
    if handle_id:
        query += "AND m.handle_id = ? "
        params = (timestamp_str, handle_id)
    
    query += "ORDER BY m.date DESC LIMIT 100"
    
    # Execute the query
    messages = query_messages_db(query, params)
    
    # Format the results
    if not messages:
        return "No messages found in the specified time period."
    
    if "error" in messages[0]:
        return f"Error accessing messages: {messages[0]['error']}"
    
    # Get chat mapping for group chat names
    chat_mapping = get_chat_mapping()
    
    formatted_messages = []
    for msg in messages:
        # Get the message content from text or attributedBody
        if msg.get('text'):
            body = msg['text']
        elif msg.get('attributedBody'):
            body = extract_body_from_attributed(msg['attributedBody'])
            if not body:
                # Skip messages with no content
                continue
        else:
            # Skip empty messages
            continue
        
        # Convert Apple timestamp to readable date
        try:
            # Convert Apple timestamp to datetime
            date_string = '2001-01-01'
            mod_date = datetime.strptime(date_string, '%Y-%m-%d')
            unix_timestamp = int(mod_date.timestamp()) * 1000000000
            
            # Handle both nanosecond and second format timestamps
            msg_timestamp = int(msg["date"])
            if len(str(msg_timestamp)) > 10:  # It's in nanoseconds
                new_date = int((msg_timestamp + unix_timestamp) / 1000000000)
            else:  # It's already in seconds
                new_date = mod_date.timestamp() + msg_timestamp
                
            date_str = datetime.fromtimestamp(new_date).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OverflowError) as e:
            # If conversion fails, use a placeholder
            date_str = "Unknown date"
            print(f"Date conversion error: {e} for timestamp {msg['date']}")
        
        direction = "You" if msg["is_from_me"] else get_contact_name(msg["handle_id"])
        
        # Check if this is a group chat
        group_chat_name = None
        if msg.get('cache_roomnames'):
            group_chat_name = chat_mapping.get(msg['cache_roomnames'])
        
        message_prefix = f"[{date_str}]"
        if group_chat_name:
            message_prefix += f" [{group_chat_name}]"
        
        formatted_messages.append(
            f"{message_prefix} {direction}: {body}"
        )
    
    if not formatted_messages:
        return "No messages found in the specified time period."
        
    return "\n".join(formatted_messages)

# Initialize the static variable for recent matches
get_recent_messages.recent_matches = []


def fuzzy_search_messages(
    search_term: str,
    hours: int = 24,
    threshold: float = 0.6,  # Default threshold adjusted for thefuzz
) -> str:
    """
    Fuzzy search for messages containing the search_term within the last N hours.

    Args:
        search_term: The string to search for in message content.
        hours: Number of hours to look back (default: 24).
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
    
    # Calculate the timestamp for X hours ago
    current_time = datetime.now(timezone.utc)
    hours_ago_dt = current_time - timedelta(hours=hours)
    apple_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
    seconds_since_apple_epoch = (hours_ago_dt - apple_epoch).total_seconds()
    
    # Convert to nanoseconds (Apple's format)
    nanoseconds_since_apple_epoch = int(seconds_since_apple_epoch * 1_000_000_000)
    timestamp_str = str(nanoseconds_since_apple_epoch)

    # Build the SQL query to get all messages in the time window
    # Limiting to 500 messages to avoid performance issues with very large message histories.
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
    ORDER BY m.date DESC
    LIMIT 500
    """
    params = (timestamp_str,)
    raw_messages = query_messages_db(query, params)

    if not raw_messages:
        return f"No messages found in the last {hours} hours to search."
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
        return f"No message content found to search in the last {hours} hours."

    # --- New fuzzy matching logic using thefuzz ---
    cleaned_search_term = clean_name(search_term).lower()
    # thefuzz scores are 0-100. Scale the input threshold (0.0-1.0).
    scaled_threshold = threshold * 100

    matched_messages_with_scores = []
    for original_message_text, msg_dict_value in message_candidates:
        # We use the original_message_text for matching, which might contain HTML entities etc.
        # clean_name will handle basic cleaning like emoji removal.
        cleaned_candidate_text = clean_name(original_message_text).lower()

        # Using WRatio for a good balance of matching strategies.
        score_from_thefuzz = fuzz.WRatio(cleaned_search_term, cleaned_candidate_text)

        if score_from_thefuzz >= scaled_threshold:
            # Store score as 0.0-1.0 for consistency with how threshold is defined
            matched_messages_with_scores.append(
                (original_message_text, msg_dict_value, score_from_thefuzz / 100.0)
            )
    matched_messages_with_scores.sort(
        key=lambda x: x[2], reverse=True
    )  # Sort by score desc

    if not matched_messages_with_scores:
        return f"No messages found matching '{search_term}' with a threshold of {threshold} in the last {hours} hours."

    chat_mapping = get_chat_mapping()
    formatted_results = []
    for _matched_text, msg_dict, score in matched_messages_with_scores:
        original_body = (
            msg_dict.get("text")
            or extract_body_from_attributed(msg_dict.get("attributedBody"))
            or "[No displayable content]"
        )

        apple_offset = (
            978307200  # Seconds between Unix epoch and Apple epoch (2001-01-01)
        )
        msg_timestamp_ns = int(msg_dict["date"])
        # Ensure timestamp is in seconds for fromtimestamp
        msg_timestamp_s = (
            msg_timestamp_ns / 1_000_000_000
            if len(str(msg_timestamp_ns)) > 10
            else msg_timestamp_ns
        )
        date_val = datetime.fromtimestamp(
            msg_timestamp_s + apple_offset, tz=timezone.utc
        )
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
        formatted_results.append(f"{message_prefix} {direction}: {original_body}")

    return (
        f"Found {len(matched_messages_with_scores)} messages matching '{search_term}':\n"
        + "\n".join(formatted_results)
    )


def _check_imessage_availability(recipient: str) -> bool:
    """
    Check if recipient has iMessage available.
    
    Args:
        recipient: Phone number or email to check
        
    Returns:
        True if iMessage is available, False otherwise
    """
    safe_recipient = recipient.replace('"', '\\"')
    
    script = f'''
    tell application "Messages"
        try
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{safe_recipient}" of targetService
            
            -- Check if buddy exists and has iMessage capability
            if targetBuddy exists then
                return "true"
            else
                return "false"
            end if
        on error
            return "false"
        end try
    end tell
    '''
    
    try:
        result = run_applescript(script)
        return result.strip().lower() == "true"
    except:
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
    safe_message = message.replace('"', '\\"').replace('\\', '\\\\')
    safe_recipient = recipient.replace('"', '\\"')
    
    script = f'''
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
    '''
    
    try:
        result = run_applescript(script)
        if result.startswith("error:"):
            return f"Error sending SMS: {result[6:]}"
        elif result.strip() == "success":
            display_name = contact_name if contact_name else recipient
            return f"SMS sent successfully to {display_name}"
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
    # Clean the inputs for AppleScript
    safe_message = message.replace('"', '\\"').replace('\\', '\\\\')
    safe_recipient = recipient.replace('"', '\\"')
    
    # For group chats, stick to iMessage only (SMS doesn't support group chats well)
    if group_chat:
        script = f'''
        tell application "Messages"
            try
                -- Try to get the existing chat
                set targetChat to chat "{safe_recipient}"
                
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
        '''
        
        try:
            result = run_applescript(script)
            if result.startswith("error:"):
                return f"Error sending group message: {result[6:]}"
            elif result.strip() == "success":
                display_name = contact_name if contact_name else recipient
                return f"Group message sent successfully to {display_name}"
            else:
                return f"Unknown group message result: {result}"
        except Exception as e:
            return f"Error sending group message: {str(e)}"
    
    # For individual messages, try iMessage first with automatic SMS fallback
    # Enhanced AppleScript with built-in fallback logic
    script = f'''
    tell application "Messages"
        try
            -- First, try iMessage
            set targetService to 1st service whose service type = iMessage
            
            try
                -- Try to get the existing buddy if possible
                set targetBuddy to buddy "{safe_recipient}" of targetService
                
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
    '''
    
    try:
        result = run_applescript(script)
        display_name = contact_name if contact_name else recipient
        
        if result.startswith("error:"):
            return f"Error sending message: {result[6:]}"
        elif result.strip() == "success:iMessage":
            return f"Message sent successfully via iMessage to {display_name}"
        elif result.strip() == "success:SMS":
            return f"Message sent successfully via SMS to {display_name} (iMessage not available)"
        elif result.strip() == "success":
            return f"Message sent successfully to {display_name}"
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
            with open(db_path, 'rb') as f:
                # Just try to read a byte to confirm access
                f.read(1)
            status.append("File is readable")
        except PermissionError:
            return f"ERROR: Permission denied when trying to read {db_path}. Please grant Full Disk Access permission to your terminal application. PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
        except Exception as e:
            return f"ERROR: Unknown error reading file: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
        
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
            return f"ERROR: Database connection error: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
        
        return "\n".join(status)
    except Exception as e:
        return f"ERROR: Unexpected error during database access check: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
    
def find_handle_by_phone(phone: str) -> Optional[int]:
    """
    Find a handle ID by phone number, trying various formats.
    Prioritizes direct message handles over group chat handles.
    
    Args:
        phone: Phone number in any format
        
    Returns:
        handle_id if found, None otherwise
    """
    # Normalize the phone number (remove all non-digit characters)
    normalized = normalize_phone_number(phone)
    if not normalized:
        return None
    
    # Try various formats for US numbers
    formats_to_try = [normalized]  # Start with the normalized input
    
    # For US numbers, try with and without country code
    if normalized.startswith('1') and len(normalized) > 10:
        # Try without the country code
        formats_to_try.append(normalized[1:])
    elif len(normalized) == 10:
        # Try with the country code
        formats_to_try.append('1' + normalized)
    
    # Enhanced query that helps distinguish between direct messages and group chats
    # We'll get all matching handles with additional context
    placeholders = ', '.join(['?' for _ in formats_to_try])
    query = f"""
    SELECT 
        h.ROWID,
        h.id,
        COUNT(DISTINCT chj.chat_id) as chat_count,
        MIN(chj.chat_id) as min_chat_id,
        GROUP_CONCAT(DISTINCT c.display_name) as chat_names
    FROM handle h
    LEFT JOIN chat_handle_join chj ON h.ROWID = chj.handle_id
    LEFT JOIN chat c ON chj.chat_id = c.ROWID
    WHERE h.id IN ({placeholders}) OR h.id IN ({placeholders})
    GROUP BY h.ROWID, h.id
    ORDER BY 
        -- Prioritize handles with fewer chats (likely direct messages)
        chat_count ASC,
        -- Then by smallest ROWID (older/more established handles)
        h.ROWID ASC
    """
    
    # Create parameters list with both the raw formats and with "+" prefix
    params = formats_to_try + ['+' + f for f in formats_to_try]
    
    results = query_messages_db(query, tuple(params))
    
    if not results or "error" in results[0]:
        return None
    
    if len(results) == 0:
        return None
    
    # Return the first result (best match based on our ordering)
    # Our query orders by chat_count ASC (direct messages first) then ROWID ASC
    return results[0]["ROWID"]

def check_addressbook_access() -> str:
    """Check if the AddressBook database is accessible and return detailed information."""
    try:
        home_dir = os.path.expanduser("~")
        sources_path = os.path.join(home_dir, "Library/Application Support/AddressBook/Sources")
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
                with open(db_path, 'rb') as f:
                    # Just try to read a byte to confirm access
                    f.read(1)
                status.append(f"File is readable: {db_path}")
            except PermissionError:
                status.append(f"ERROR: Permission denied when trying to read {db_path} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE.")
                continue
            except Exception as e:
                status.append(f"ERROR: Unknown error reading file {db_path}: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE.")
                continue
            
            # Try to connect to the database
            try:
                conn = sqlite3.connect(db_path)
                status.append(f"Successfully connected to database: {db_path}")
                
                # Test a simple query
                cursor = conn.cursor()
                cursor.execute("SELECT count(*) FROM sqlite_master")
                count = cursor.fetchone()[0]
                status.append(f"Database contains {count} tables")
                
                # Check if the necessary tables exist
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('ZABCDRECORD', 'ZABCDPHONENUMBER')")
                tables = [row[0] for row in cursor.fetchall()]
                if 'ZABCDRECORD' in tables and 'ZABCDPHONENUMBER' in tables:
                    status.append("Required tables (ZABCDRECORD, ZABCDPHONENUMBER) are present")
                else:
                    status.append(f"WARNING: Some required tables are missing. Found: {', '.join(tables)}")
                
                # Get a count of contacts
                try:
                    cursor.execute("SELECT COUNT(*) FROM ZABCDRECORD")
                    contact_count = cursor.fetchone()[0]
                    status.append(f"Database contains {contact_count} contacts")
                except sqlite3.OperationalError:
                    status.append("Could not query contact count PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE.")
                
                conn.close()
            except sqlite3.OperationalError as e:
                status.append(f"ERROR: Database connection error for {db_path}: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE.")
        
        # Try to get actual contacts
        contacts = get_addressbook_contacts()
        if contacts:
            status.append(f"Successfully retrieved {len(contacts)} contacts with phone numbers")
        else:
            status.append("WARNING: No contacts with phone numbers found. PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE.")
        
        return "\n".join(status)
    except Exception as e:
        return f"ERROR: Unexpected error during database access check: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."