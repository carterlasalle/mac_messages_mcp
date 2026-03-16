"""
Tests for the messages module
"""
import unittest
from unittest.mock import patch, MagicMock

from mac_messages_mcp.messages import run_applescript, get_messages_db_path, query_messages_db, extract_body_from_attributed

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

class TestExtractBodyFromAttributed(unittest.TestCase):
    """Tests for extract_body_from_attributed"""

    def _build_blob(self, text):
        """Build a minimal typedstream blob with the given text content"""
        encoded = text.encode("utf-8")
        length = len(encoded)
        # NSString marker + 5-byte header (\x01\x00\x84\x01+) + length byte + text
        if length < 0x80:
            length_bytes = bytes([length])
        else:
            # 0x81 prefix for 2-byte LE length
            length_bytes = b"\x81" + length.to_bytes(2, "little")
        return b"prefix" + b"NSString" + b"\x01\x00\x84\x01+" + length_bytes + encoded + b"trailing"

    def test_none_returns_none(self):
        """Test that None input returns None"""
        # Run function
        result = extract_body_from_attributed(None)

        # Check results
        self.assertIsNone(result)

    def test_empty_bytes_returns_none(self):
        """Test that empty bytes returns None"""
        # Run function
        result = extract_body_from_attributed(b"")

        # Check results
        self.assertIsNone(result)

    def test_garbage_bytes_returns_none(self):
        """Test that random bytes return None without crashing"""
        # Run function
        result = extract_body_from_attributed(b"\x00\x01\x02\x03")

        # Check results
        self.assertIsNone(result)

    def test_valid_short_message(self):
        """Test extracting a short message (length < 0x80)"""
        # Setup
        blob = self._build_blob("Hello")

        # Run function
        result = extract_body_from_attributed(blob)

        # Check results
        self.assertEqual(result, "Hello")

    def test_valid_longer_message(self):
        """Test extracting a message with 2-byte length encoding"""
        # Setup
        content = "A" * 200  # > 0x7F, triggers 0x81 length prefix
        blob = self._build_blob(content)

        # Run function
        result = extract_body_from_attributed(blob)

        # Check results
        self.assertEqual(result, content)

    def test_no_nsstring_marker(self):
        """Test that missing NSString marker returns None"""
        # Setup
        body = b"prefix data with no marker trailing"

        # Run function
        result = extract_body_from_attributed(body)

        # Check results
        self.assertIsNone(result)

    def test_truncated_after_nsstring(self):
        """Test that truncated data after NSString returns None"""
        # Setup - NSString marker but not enough bytes for header
        body = b"NSString\x01\x00"

        # Run function
        result = extract_body_from_attributed(body)

        # Check results
        self.assertIsNone(result)

    def test_random_binary_does_not_crash(self):
        """Test that random binary data doesn't raise exceptions"""
        import os

        # Setup
        random_data = os.urandom(1024)

        # Run function - should not raise
        result = extract_body_from_attributed(random_data)

        # Check results
        self.assertIn(type(result), (str, type(None)))

if __name__ == '__main__':
    unittest.main()