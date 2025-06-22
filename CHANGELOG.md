# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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