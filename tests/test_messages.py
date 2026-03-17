"""
Tests for the messages module
"""
import unittest
from unittest.mock import patch, MagicMock

from mac_messages_mcp.messages import run_applescript, get_messages_db_path, query_messages_db, _escape_for_applescript

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

class TestEscapeForAppleScript(unittest.TestCase):
    """Tests for the _escape_for_applescript helper"""

    def test_plain_text_unchanged(self):
        """Test that plain text passes through unchanged"""
        # Run function
        result = _escape_for_applescript('hello world')

        # Check results
        self.assertEqual(result, 'hello world')

    def test_quotes_escaped(self):
        """Test that double quotes are escaped"""
        # Run function
        result = _escape_for_applescript('say "hello"')

        # Check results
        self.assertEqual(result, 'say \\"hello\\"')

    def test_backslashes_escaped(self):
        """Test that backslashes are escaped"""
        # Run function
        result = _escape_for_applescript('path\\to\\file')

        # Check results
        self.assertEqual(result, 'path\\\\to\\\\file')

    def test_escape_order_prevents_injection(self):
        """Test that backslashes are escaped before quotes to prevent injection"""
        # Setup - a string with backslash-quote that could break AppleScript if
        # quotes are escaped first (producing \\" which unescapes the quote)
        malicious = 'test\\"injection'

        # Run function
        result = _escape_for_applescript(malicious)

        # Check results - backslash escaped first, then quote
        # Input:  test\"injection
        # Step 1: test\\"injection  (backslash escaped)
        # Step 2: test\\\\"injection  (quote escaped)
        self.assertEqual(result, 'test\\\\\\"injection')
        # The result should NOT contain an unescaped quote
        self.assertNotIn('\\"', result.replace('\\\\"', ''))

    def test_empty_string(self):
        """Test that empty string returns empty string"""
        # Run function
        result = _escape_for_applescript('')

        # Check results
        self.assertEqual(result, '')

    def test_unicode_unchanged(self):
        """Test that unicode characters pass through unchanged"""
        # Run function
        result = _escape_for_applescript('Hello 世界')

        # Check results
        self.assertEqual(result, 'Hello 世界')

if __name__ == '__main__':
    unittest.main() 