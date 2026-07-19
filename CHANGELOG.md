# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-18

### Added
- Added production macOS CI across Python 3.10, 3.11, 3.12, and 3.13 with formatting, typing, distribution-build, clean-wheel-install, and MCPB architecture checks.
- Added structured GitHub issue forms and a pull-request template with validation and privacy prompts.
- Added complete setup guidance for Claude Desktop, Claude Code, Codex, Cursor, VS Code, and other stdio MCP clients.
- Added focused regression coverage for Messages and AddressBook database access failures.

### Changed
- Declared the project production-stable and established the first supported `1.x` compatibility contract.
- Replaced the interactive regex-based version script with an atomic, non-interactive UV-backed workflow that synchronizes `pyproject.toml`, `uv.lock`, and `manifest.json`.
- Made releases idempotent and reviewable: merged version changes are validated, published to PyPI through OIDC trusted publishing, annotated with a Git tag, and published as a GitHub release.
- Reworked the README around an install, permissions, client configuration, verification, privacy, and troubleshooting flow.

### Security
- Hardened local database access with SQLite read-only mode and `query_only` enforcement.
- Bounded and sanitized message output, escaped AppleScript inputs, and added execution timeouts around Messages automation.
- Kept attachment discovery metadata-first, with explicit fetches and size limits for inline images.
- Preserved tokenless PyPI publishing; no long-lived package index credential is stored in GitHub.

### Fixed
- Normalized direct phone recipients to reliable E.164 values and improved contact result formatting.
- Improved group-chat filtering, attachment handling, package installation verification, and permission diagnostics.

### Compatibility
- No intentional breaking Python or MCP tool API changes were introduced from 0.9.2; `1.0.0` marks the stable support boundary.

## [0.9.2] - 2026-05-10

### Added
- Added `chat_id` filtering to `tool_get_recent_messages` for group conversations returned by `tool_get_chats`.

### Fixed
- Normalized phone recipients to send-ready E.164-style values before dispatching to Messages.
- Made fuzzy contact lookup return send-ready phone numbers with a leading `+`.

## [0.9.1] - 2026-05-06

### Added
- Added `glama.json` metadata for Glama server ownership and profile completion.

### Changed
- Expanded MCP tool descriptions and parameter schemas with permissions, side-effect, return-shape, and tool-selection guidance.
- Updated Claude Desktop extension metadata to match the current package version.
- Modernized package license metadata to avoid setuptools deprecation warnings.

## [0.9.0] - 2026-05-06

### Added
- Added message attachment discovery, metadata search, and attachment fetching.
- Added Claude Desktop Extension packaging metadata.
- Added Dockerfile and packaging documentation for catalog and local inspection workflows.

### Fixed
- Hardened message output rendering for control characters, embedded newlines, and oversized message bodies.
- Resolved outstanding pull requests and issue-reported test coverage gaps.

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
