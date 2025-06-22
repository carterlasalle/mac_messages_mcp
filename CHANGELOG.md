# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2024-12-28

### 🚀 MAJOR FEATURE: SMS/RCS Fallback Support

This release adds automatic SMS/RCS fallback when recipients don't have iMessage, solving the "Not Delivered" problem for Android users and significantly improving message delivery reliability.

### Added
- **Automatic SMS/RCS Fallback**: Messages automatically fall back to SMS when iMessage is unavailable
- **iMessage Availability Checking**: New `tool_check_imessage_availability` MCP tool to check recipient capabilities
- **Enhanced Message Sending**: Improved AppleScript logic with built-in fallback detection
- **Clear Service Feedback**: Users are informed whether message was sent via iMessage or SMS
- **Android Compatibility**: Now works seamlessly with Android users and non-iMessage contacts

### Enhanced
- **Message Sending Logic**: Enhanced `_send_message_direct()` with automatic fallback
- **AppleScript Integration**: Improved error handling and service detection
- **User Experience**: Significantly reduced "Not Delivered" errors
- **Debugging Support**: Better visibility into delivery methods and failures

### New Functions
- `_check_imessage_availability()`: Check if recipient has iMessage available
- `_send_message_sms()`: Direct SMS sending function with proper error handling
- Enhanced fallback logic in existing message sending functions

### New MCP Tool
- `tool_check_imessage_availability`: Check recipient iMessage status with clear feedback
  - ✅ Shows iMessage available
  - 📱 Shows SMS fallback available
  - ❌ Shows when neither service is available

### Technical Implementation
- **Smart Detection**: Automatically detects phone numbers vs email addresses
- **Service Prioritization**: Tries iMessage first, falls back to SMS for phone numbers
- **Group Chat Handling**: Maintains iMessage-only for group chats (SMS doesn't support groups well)
- **Error Differentiation**: Distinguishes between iMessage and SMS delivery failures

### Testing
- Added `test_sms_fallback_functionality()` to integration test suite
- Validates new SMS functions don't crash with import errors
- Ensures proper exception handling for AppleScript operations
- Maintains backward compatibility with existing functionality

### Use Cases Solved
- **Android Users**: Messages now deliver automatically via SMS instead of failing
- **Mixed Contacts**: Seamless experience across iMessage and SMS contacts
- **Delivery Troubleshooting**: Can check iMessage availability before sending
- **Reduced Friction**: No manual intervention needed for cross-platform messaging

### Migration Notes
Users upgrading from 0.6.7 will immediately benefit from:
1. **Improved Delivery**: Messages to Android users work automatically
2. **Better Feedback**: Clear indication of delivery method used
3. **New Debugging**: Check iMessage availability proactively
4. **Fewer Errors**: Significantly reduced "Not Delivered" messages

This release makes Mac Messages MCP truly universal - working seamlessly with both iMessage and SMS/RCS recipients.

## [0.6.7] - 2024-12-19

### 🚨 CRITICAL FIXES
- **FIXED**: Added missing `from thefuzz import fuzz` import that caused fuzzy search to crash with NameError
- **FIXED**: Corrected timestamp conversion from seconds to nanoseconds for Apple's Core Data format
- **FIXED**: Added comprehensive input validation to prevent integer overflow crashes
- **FIXED**: Improved contact selection validation with better error messages

### Added
- Input validation for negative hours (now returns helpful error instead of processing)
- Maximum hours limit (87,600 hours / 10 years) to prevent integer overflow
- Comprehensive integration tests to catch runtime failures
- Better error messages for invalid contact selections
- Validation for fuzzy search thresholds (must be 0.0-1.0)
- Empty search term validation for fuzzy search

### Fixed
- **Message Retrieval**: Fixed timestamp calculation that was causing most time ranges to return no results
- **Fuzzy Search**: Fixed missing import that caused crashes when using fuzzy message search
- **Integer Overflow**: Fixed crashes when using very large hour values
- **Contact Selection**: Fixed misleading error messages for invalid contact IDs
- **Error Handling**: Standardized error message format across all functions

### Changed
- Timestamp calculation now uses nanoseconds instead of seconds (matches Apple's format)
- Error messages now consistently start with "Error:" for better user experience
- Contact selection validation is more robust and provides clearer guidance

### Technical Details
This release fixes catastrophic failures discovered through real-world testing:
- Message retrieval was returning 6 messages from a year of data due to incorrect timestamp format
- Fuzzy search was completely non-functional due to missing import
- Large hour values caused integer overflow crashes
- Invalid inputs were accepted then caused crashes instead of validation errors

### Breaking Changes
None - all changes are backward compatible while fixing broken functionality.

## [0.6.6] - 2024-12-18

### Issues Identified (Fixed in 0.6.7)
- Missing `thefuzz` import causing fuzzy search crashes
- Incorrect timestamp calculation causing poor message retrieval
- No input validation causing integer overflow crashes
- Inconsistent error handling and misleading error messages

## Previous Versions
[Previous changelog entries would go here] 