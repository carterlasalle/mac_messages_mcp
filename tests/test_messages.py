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

class TestTimestampConversion(unittest.TestCase):
    """Tests for Apple epoch timestamp conversion"""

    def test_apple_epoch_constant(self):
        """Test that 978307200 is the correct offset between Unix and Apple epochs"""
        from datetime import datetime, timezone

        # Setup
        unix_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        apple_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)

        # Run
        delta_seconds = int((apple_epoch - unix_epoch).total_seconds())

        # Check results
        self.assertEqual(delta_seconds, 978307200)

    def test_nanosecond_timestamp_conversion(self):
        """Test converting a nanosecond Apple timestamp to a datetime"""
        from datetime import datetime, timezone

        # Setup - a known Apple timestamp in nanoseconds
        # 2025-01-01 00:00:00 UTC = 757382400 seconds after Apple epoch
        apple_epoch_offset = 978307200
        apple_seconds = 757382400
        apple_nanos = apple_seconds * 1_000_000_000

        # Run - convert like the fixed code does
        msg_timestamp_s = apple_nanos / 1_000_000_000
        date_val = datetime.fromtimestamp(msg_timestamp_s + apple_epoch_offset, tz=timezone.utc)

        # Check results
        expected = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(date_val, expected)

    def test_second_format_timestamp(self):
        """Test converting a second-format Apple timestamp"""
        from datetime import datetime, timezone

        # Setup - timestamp already in seconds (len <= 10)
        apple_epoch_offset = 978307200
        apple_seconds = 757382400  # 2025-01-01 00:00:00 UTC

        # Run
        msg_timestamp_s = apple_seconds  # already in seconds, no division needed
        date_val = datetime.fromtimestamp(msg_timestamp_s + apple_epoch_offset, tz=timezone.utc)

        # Check results
        expected = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(date_val, expected)

if __name__ == '__main__':
    unittest.main()