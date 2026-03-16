"""
Tests for the messages module
"""
import unittest
from unittest.mock import patch, MagicMock

import os
import sqlite3
import tempfile

from mac_messages_mcp.messages import run_applescript, get_messages_db_path, query_messages_db, get_chat_mapping

class TestMessages(unittest.TestCase):
    """Tests for the messages module"""
    
    @patch('subprocess.Popen')
    def test_run_applescript_success(self, mock_popen):
        """Test running AppleScript successfully"""
        # Setup mock
        process_mock = MagicMock()
        process_mock.returncode = 0
        process_mock.communicate.return_value = (b'Success', b'')
        mock_popen.return_value = process_mock
        
        # Run function
        result = run_applescript('tell application "Messages" to get name')
        
        # Check results
        self.assertEqual(result, 'Success')
        mock_popen.assert_called_with(
            ['osascript', '-e', 'tell application "Messages" to get name'],
            stdout=-1, 
            stderr=-1
        )
    
    @patch('subprocess.Popen')
    def test_run_applescript_error(self, mock_popen):
        """Test running AppleScript with error"""
        # Setup mock
        process_mock = MagicMock()
        process_mock.returncode = 1
        process_mock.communicate.return_value = (b'', b'Error message')
        mock_popen.return_value = process_mock
        
        # Run function
        result = run_applescript('invalid script')
        
        # Check results
        self.assertEqual(result, 'Error: Error message')
    
    @patch('os.path.expanduser')
    def test_get_messages_db_path(self, mock_expanduser):
        """Test getting the Messages database path"""
        # Setup mock
        mock_expanduser.return_value = '/Users/testuser'
        
        # Run function
        result = get_messages_db_path()
        
        # Check results
        self.assertEqual(result, '/Users/testuser/Library/Messages/chat.db')
        mock_expanduser.assert_called_with('~')

class TestGetChatMapping(unittest.TestCase):
    """Tests for get_chat_mapping error handling"""

    @patch('mac_messages_mcp.messages.get_messages_db_path')
    def test_returns_mapping(self, mock_path):
        """Test happy path returns dict of room_name -> display_name"""
        # Setup - create a temp DB with the expected schema
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            mock_path.return_value = db_path
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE chat (room_name TEXT, display_name TEXT)")
            conn.execute("INSERT INTO chat VALUES ('room1', 'Alice')")
            conn.execute("INSERT INTO chat VALUES ('room2', 'Bob')")
            conn.commit()
            conn.close()

            # Run function
            result = get_chat_mapping()

            # Check results
            self.assertEqual(result, {"room1": "Alice", "room2": "Bob"})
        finally:
            os.unlink(db_path)

    @patch('mac_messages_mcp.messages.get_messages_db_path')
    def test_inaccessible_db_returns_empty_dict(self, mock_path):
        """Test that inaccessible database returns empty dict instead of crashing"""
        # Setup
        mock_path.return_value = "/nonexistent/path/chat.db"

        # Run function
        result = get_chat_mapping()

        # Check results
        self.assertEqual(result, {})

    @patch('mac_messages_mcp.messages.get_messages_db_path')
    def test_empty_table_returns_empty_dict(self, mock_path):
        """Test that empty chat table returns empty dict"""
        # Setup
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            mock_path.return_value = db_path
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE chat (room_name TEXT, display_name TEXT)")
            conn.commit()
            conn.close()

            # Run function
            result = get_chat_mapping()

            # Check results
            self.assertEqual(result, {})
        finally:
            os.unlink(db_path)

if __name__ == '__main__':
    unittest.main()