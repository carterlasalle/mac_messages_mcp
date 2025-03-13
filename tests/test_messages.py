"""
Tests for the messages module
"""
import unittest
from unittest.mock import patch, MagicMock

from mac_messages_mcp.messages import run_applescript, get_messages_db_path, query_messages_db

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

if __name__ == '__main__':
    unittest.main() 