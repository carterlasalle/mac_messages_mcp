# Technical Context

## Technology Stack

### Core Technologies
- **Python 3.10+**: Modern Python with type hints and async support
- **uv**: Fast Python package manager (required for installation)
- **SQLite3**: Direct database access for Messages and AddressBook
- **FastMCP**: MCP server framework for AI assistant integration
- **AppleScript**: Native macOS automation for message sending

### Key Dependencies - ACTUAL USAGE STATUS
```toml
# Core dependencies
mcp[cli] = "*"                    # MCP protocol with CLI support - USED
thefuzz = ">=0.20.0"             # Fuzzy string matching - DECLARED BUT NOT IMPORTED
python-Levenshtein = ">=0.23.0"  # Performance boost for fuzzy matching - UNUSED

# Development dependencies  
pytest = ">=7.0.0"               # Testing framework - INSUFFICIENT COVERAGE
black = ">=23.0.0"               # Code formatting - WORKING
isort = ">=5.10.0"               # Import sorting - WORKING  
mypy = ">=1.0.0"                 # Type checking - PASSES BUT MISSES RUNTIME ERRORS
```

### Critical Dependency Issue
- **thefuzz Listed**: Declared in pyproject.toml as core dependency
- **thefuzz Never Imported**: Missing `from thefuzz import fuzz` in messages.py
- **Runtime Crash**: Any call to `tool_fuzzy_search_messages` fails with NameError
- **Production Impact**: Published package has broken advertised functionality

### Platform Requirements
- **macOS 11+**: Required for Messages database access
- **Full Disk Access**: Essential permission for database reading
- **Messages App**: Must be configured and active
- **Python 3.10+**: Modern Python features required

## Development Setup

### Installation Methods
```bash
# Method 1: From PyPI (recommended but contains bugs)
uv pip install mac-messages-mcp

# Method 2: From source (development)
git clone https://github.com/carterlasalle/mac_messages_mcp.git
cd mac_messages_mcp
uv install -e .
```

### Permission Configuration
1. **System Preferences** → **Security & Privacy** → **Privacy** → **Full Disk Access**
2. Add terminal application (Terminal, iTerm2, etc.)
3. Add AI assistant application (Claude Desktop, Cursor)
4. Restart applications after granting permissions

### Integration Setup

#### Claude Desktop
```json
{
    "mcpServers": {
        "messages": {
            "command": "uvx",
            "args": ["mac-messages-mcp"]
        }
    }
}
```

#### Cursor
```
uvx mac-messages-mcp
```

**Note**: Integration works for most tools but crashes on fuzzy search usage.

## Technical Constraints

### macOS Specific Limitations
- **Database Locations**: Fixed paths in `~/Library/Messages/` and `~/Library/Application Support/AddressBook/`
- **Permission Model**: Requires Full Disk Access, cannot work with restricted permissions
- **AppleScript Dependency**: Message sending requires Messages app and AppleScript support
- **Sandbox Limitations**: Cannot work in sandboxed environments

### Database Access Constraints
- **Read-Only Access**: Messages database is read-only to prevent corruption
- **SQLite Limitations**: Direct database access while Messages app is running
- **Schema Dependencies**: Relies on Apple's internal database schema (subject to change)
- **Contact Integration**: AddressBook database structure varies by macOS version

### Performance Limitations
- **Database Size**: Large message histories may impact query performance
- **Contact Matching**: Fuzzy matching performance scales with contact count
- **Memory Usage**: Large result sets loaded into memory for processing
- **AppleScript Timing**: Message sending has inherent delays due to AppleScript execution

### Critical Runtime Limitations
- **Import Errors**: Fuzzy search functionality completely broken due to missing import
- **No Integration Testing**: Runtime crashes not caught during development
- **Partial Functionality**: Only 7 of 8 MCP tools work correctly

## Architecture Decisions

### Direct Database Access
**Decision**: Access SQLite databases directly rather than using APIs
**Reasoning**: 
- Messages app lacks comprehensive API
- Direct access provides fastest, most reliable data retrieval
- Avoids complex screen scraping or automation
**Trade-offs**: Requires system permissions, schema dependency

### MCP Protocol Choice
**Decision**: Use FastMCP for server implementation
**Reasoning**:
- Standard protocol for AI assistant integration
- Supports multiple AI platforms (Claude, Cursor)
- Clean tool-based interface design
**Trade-offs**: Limited to MCP-compatible assistants

### Fuzzy Matching Strategy - BROKEN IMPLEMENTATION
**Decision**: Attempt to use thefuzz library for message search
**Reality**: 
- ❌ thefuzz never imported, causing runtime crashes
- ✅ difflib used for contact matching (works correctly)
- Documentation claims thefuzz integration but implementation missing
**Trade-offs**: Major feature completely non-functional

### Contact Caching Approach
**Decision**: In-memory cache with 5-minute TTL
**Reasoning**:
- AddressBook queries are expensive
- Contact data changes infrequently
- Balance between performance and data freshness
**Trade-offs**: Memory usage, stale data possibility

## Development Workflow

### Version Management
- **Semantic Versioning**: MAJOR.MINOR.PATCH pattern
- **Automated Bumping**: `scripts/bump_version.py` for consistent updates
- **Git Tags**: Version tags trigger automated PyPI publishing
- **CI/CD Pipeline**: GitHub Actions for build and publish workflow
- **Quality Issue**: Broken code published to PyPI as version 0.6.6

### Testing Strategy - INSUFFICIENT
- **Unit Tests**: Basic functionality testing in `tests/`
- **Permission Testing**: Validate database access scenarios
- **Integration Testing**: **MISSING** - Would have caught import error
- **Manual Testing**: **INSUFFICIENT** - Fuzzy search never tested

### Code Quality - MIXED RESULTS
- **Type Hints**: Full type annotation throughout codebase
- **Black Formatting**: Consistent code style enforcement
- **Import Sorting**: isort for clean import organization
- **Linting**: mypy for static type checking - **PASSES BUT MISSES RUNTIME ERRORS**

## Database Schema Dependencies

### Messages Database (`chat.db`)
```sql
-- Key tables and fields used
message (ROWID, date, text, attributedBody, is_from_me, handle_id, cache_roomnames)
handle (ROWID, id)  -- Phone numbers and emails
chat (ROWID, chat_identifier, display_name, room_name)
chat_handle_join (chat_id, handle_id)
```

### AddressBook Database (`AddressBook-v22.abcddb`)
```sql
-- Contact information tables
ZABCDRECORD (Z_PK, ZFIRSTNAME, ZLASTNAME)
ZABCDPHONENUMBER (ZOWNER, ZFULLNUMBER, ZORDERINGINDEX)
```

## Deployment and Distribution

### PyPI Publishing - PUBLISHES BROKEN CODE
- **Automated Process**: Git tag triggers GitHub Actions workflow
- **Version Synchronization**: Automatic version updates across files
- **Build Process**: uv build creates distribution packages
- **Publishing**: uv publish handles PyPI upload
- **Quality Gate Missing**: No integration testing prevents broken releases

### Entry Points
```toml
[project.scripts]
mac-messages-mcp = "mac_messages_mcp.server:run_server"
mac_messages_mcp = "mac_messages_mcp.server:run_server"  # Alternative name
```

### Security Considerations
- **Database Access**: Read-only to prevent data corruption
- **Permission Validation**: Proactive checking with user guidance
- **Error Handling**: Secure error messages without exposing system details
- **Data Privacy**: No data logging or external transmission

## Critical Implementation Analysis

### Import Dependencies Reality Check
```python
# Current imports in messages.py (lines 1-13):
import os
import re
import sqlite3
import subprocess
import json
import time
import difflib                                    # USED for contact matching
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
import glob

# MISSING CRITICAL IMPORT:
# from thefuzz import fuzz                       # NEVER IMPORTED
```

### Broken Fuzzy Search Implementation
```python
# Line 774-901: fuzzy_search_messages function
# Line 846: The crash point
score_from_thefuzz = fuzz.WRatio(cleaned_search_term, cleaned_candidate_text)
#                    ^^^^ NameError: name 'fuzz' is not defined
```

### Working vs Broken Functionality Map
- ✅ **Contact Fuzzy Matching**: Uses `difflib.SequenceMatcher` - WORKS
- ✅ **Database Operations**: SQLite access - WORKS  
- ✅ **AppleScript Integration**: Message sending - WORKS
- ✅ **MCP Server**: FastMCP implementation - WORKS
- ❌ **Message Fuzzy Search**: Uses undefined `fuzz` module - BROKEN

### Dependency Confusion
- **pyproject.toml declares**: `thefuzz>=0.20.0` as dependency
- **Code attempts to use**: `fuzz.WRatio()` from thefuzz
- **Import statement**: **MISSING** - Never added to imports
- **Result**: Dependency installed but never accessible to code

## Quality Assurance Gaps

### Testing Failures
- **Static Analysis**: mypy passes but doesn't catch runtime import errors
- **Unit Tests**: Only test basic functions, not integration scenarios
- **Manual Testing**: Fuzzy search feature never manually tested
- **CI/CD**: Builds and publishes broken code automatically

### Documentation vs Reality
- **Claims**: "thefuzz integration for better message content matching"
- **Reality**: thefuzz never imported, feature crashes
- **Impact**: Users install package expecting working fuzzy search
- **Trust**: Documentation completely inaccurate about core feature

### Recommended Fixes
1. **Immediate**: Add `from thefuzz import fuzz` to messages.py imports
2. **Testing**: Add integration tests that actually call all MCP tools
3. **Quality Gates**: Prevent publishing without full functionality testing
4. **Documentation**: Audit all claims against actual working features

## Architecture Assessment

### Strengths
- **Clean MCP Integration**: Professional protocol implementation
- **Robust Database Access**: Solid SQLite handling with error recovery
- **Effective Caching**: Smart performance optimizations
- **Good Separation of Concerns**: Clean architectural boundaries

### Critical Weaknesses  
- **Broken Core Feature**: Advertised functionality doesn't work
- **No Integration Testing**: Runtime failures not caught
- **Quality Assurance Gaps**: Basic development oversights reach production
- **Documentation Fraud**: Claims working features that crash

The technical foundation is solid, but the project fails basic quality assurance standards by publishing broken code with inaccurate documentation.