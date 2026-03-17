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

class TestSendMessageToRecipient(unittest.TestCase):
    """Tests for _send_message_to_recipient escaping"""

    @patch('mac_messages_mcp.messages.run_applescript')
    def test_does_not_raise_name_error(self, mock_applescript):
        """Test that safe_recipient is defined (was NameError after merge)"""
        from mac_messages_mcp.messages import _send_message_to_recipient

        # Setup mock
        mock_applescript.return_value = 'Success'

        # Run function — this raised NameError before the fix
        result = _send_message_to_recipient('+15551234567', 'hello')

        # Check results
        self.assertIn('sent successfully', result)

    @patch('mac_messages_mcp.messages.run_applescript')
    def test_recipient_with_quotes_is_escaped(self, mock_applescript):
        """Test that quotes in recipient don't break the AppleScript command"""
        from mac_messages_mcp.messages import _send_message_to_recipient

        # Setup mock
        mock_applescript.return_value = 'Success'

        # Run function with a recipient containing quotes
        _send_message_to_recipient('+1234"567', 'hello')

        # Check results — the AppleScript command should have escaped quotes
        call_args = mock_applescript.call_args[0][0]
        self.assertIn('+1234\\"567', call_args)
        self.assertNotIn('"+1234"567"', call_args)

if __name__ == '__main__':
    unittest.main() 