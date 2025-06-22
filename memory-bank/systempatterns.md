# System Patterns

## Architecture Overview

### Core Components
```
┌─────────────────┐    ┌─────────────────┐
│   AI Assistant  │    │   MCP Client    │
│ (Claude/Cursor) │◄──►│    (Built-in)   │
└─────────────────┘    └─────────────────┘
                               │
                               ▼
                       ┌─────────────────┐
                       │   MCP Server    │
                       │  (FastMCP)      │
                       └─────────────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
        │   Messages   │ │ AddressBook  │ │ AppleScript  │
        │  Database    │ │  Database    │ │   Engine     │
        └──────────────┘ └──────────────┘ └──────────────┘
```

### Layer Separation

#### MCP Server Layer (`server.py`)
- **Purpose**: Protocol interface between AI assistants and message functionality
- **Pattern**: Tool-based API with clear function signatures
- **Responsibilities**: 
  - Request validation and parameter handling
  - Error translation for user-friendly responses
  - Tool orchestration and workflow management
- **Critical Issue**: One tool (`tool_fuzzy_search_messages`) will crash due to import error

#### Business Logic Layer (`messages.py`)
- **Purpose**: Core message and contact operations
- **Pattern**: Pure functions with minimal external dependencies
- **Responsibilities**:
  - Database querying and data transformation
  - Contact resolution and fuzzy matching (using difflib)
  - Message sending via AppleScript
  - Permission and access validation
- **Critical Bug**: `fuzzy_search_messages` function uses undefined `fuzz` module

#### Data Access Layer
- **SQLite Direct Access**: Messages (`chat.db`) and AddressBook databases
- **AppleScript Integration**: Native message sending through Messages app
- **File System Access**: Database location detection and validation

## Key Design Patterns

### Database Access Pattern
```python
# Consistent error handling for database operations
def query_messages_db(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        # Connection and query logic
        return results
    except sqlite3.OperationalError as e:
        # Specific permission error handling
        return [{"error": "Permission denied message with guidance"}]
    except Exception as e:
        # Generic error fallback
        return [{"error": str(e)}]
```

### Contact Resolution Pattern - WORKING
- **Primary**: Exact match on normalized phone numbers
- **Secondary**: Fuzzy matching on contact names using `difflib.SequenceMatcher`
- **Tertiary**: User disambiguation when multiple matches
- **Caching**: In-memory contact cache with TTL for performance

**Implementation Detail**: Contact fuzzy matching works because it uses Python's built-in `difflib` library, not the missing `thefuzz` import.

### Message Processing Pattern
```python
# Unified message content extraction
def extract_message_content(msg_dict):
    if msg_dict.get('text'):
        return msg_dict['text']  # Plain text
    elif msg_dict.get('attributedBody'):
        return extract_body_from_attributed(msg_dict['attributedBody'])  # Rich content
    return None  # Skip empty messages
```

### Error Recovery Pattern
- **Permission Issues**: Clear guidance with specific setup instructions
- **Ambiguous Contacts**: Present numbered options for user selection
- **Database Access**: Fallback methods when primary access fails
- **Missing Data**: Graceful degradation with partial results
- **Import Errors**: **NONE** - Code crashes with NameError

## Component Relationships

### MCP Tool Registration - REALITY CHECK
Tool status after comprehensive testing:
- ❌ `tool_get_recent_messages`: **CATASTROPHICALLY BROKEN** - 6 messages from a year of data
- ✅ `tool_send_message`: Message sending with contact resolution - CLAIMED WORKING
- ✅ `tool_find_contact`: Contact search and disambiguation - WORKING (349 contacts)
- ❌ `tool_fuzzy_search_messages`: Content-based message search - **CRASHES** (import error)
- ✅ `tool_check_db_access`: Database diagnostics - WORKING  
- ✅ `tool_check_contacts`: Contact listing - WORKING
- ✅ `tool_check_addressbook`: AddressBook diagnostics - WORKING
- ✅ `tool_get_chats`: Group chat listing - STATUS UNKNOWN

**CRITICAL**: 2 of 8 tools are completely broken, making the entire system unreliable.

### State Management
- **Stateless Operations**: Each tool call is independent
- **Caching Strategy**: Contact data cached for performance
- **Session Context**: Recent contact matches stored for disambiguation  
- **Crash State**: Multiple tools cause server errors or return no useful data

### Permission Model
- **Validation First**: Check database access before operations - WORKING
- **User Guidance**: Specific error messages with solution steps - WORKING
- **Graceful Degradation**: **FAILED** - Tools crash instead of degrading gracefully

## Data Flow Patterns

### Message Reading Flow - COMPLETELY BROKEN
1. **Time Calculation**: Convert hours to Apple epoch timestamp - **BROKEN LOGIC**
2. **Database Query**: SQLite query with timestamp filtering - **RETURNS ALMOST NO DATA**
3. **Content Extraction**: Handle both text and attributedBody formats - UNREACHABLE
4. **Contact Resolution**: Map handle_ids to human-readable names - UNREACHABLE  
5. **Formatting**: Present in chronological order with metadata - UNREACHABLE

**Reality**: Steps 3-5 never execute because step 2 returns no data due to broken SQL logic.

### Message Sending Flow - CLAIMED WORKING
1. **Contact Resolution**: Name → Phone number mapping - CLAIMED WORKING
2. **Disambiguation**: Handle multiple matches with user choice - CLAIMED WORKING
3. **AppleScript Generation**: Dynamic script creation - STATUS UNKNOWN
4. **Execution**: Native Messages app integration - STATUS UNKNOWN
5. **Confirmation**: Success/error feedback to user - STATUS UNKNOWN

### Contact Search Flow - WORKING
1. **Fuzzy Matching**: Using `difflib.SequenceMatcher` (not thefuzz) - WORKING
2. **Scoring**: Weighted results by match quality - WORKING
3. **Threshold Filtering**: Remove low-confidence matches - WORKING
4. **Ranking**: Sort by relevance score - WORKING
5. **Presentation**: Clear options for user selection - WORKING

### Fuzzy Message Search Flow - COMPLETELY BROKEN
1. **Time Calculation**: Convert hours to Apple epoch timestamp - **BROKEN SAME AS MESSAGE READING**
2. **Database Query**: SQLite query with timestamp filtering - **RETURNS ALMOST NO DATA**
3. **Content Extraction**: Handle both text and attributedBody formats - UNREACHABLE
4. **Fuzzy Matching**: **CRASHES** at `fuzz.WRatio()` call - IMPORT ERROR
5. **Never Reached**: All subsequent steps unreachable due to multiple failures

## Critical Implementation Issues

### SQL Query Logic - CATASTROPHIC FAILURE
The core message retrieval SQL is fundamentally broken:
```python
# Suspected broken logic in get_recent_messages():
current_time = datetime.now(timezone.utc)
hours_ago = current_time - timedelta(hours=hours)
apple_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
seconds_since_apple_epoch = int((hours_ago - apple_epoch).total_seconds())

# Real testing results prove this calculation or SQL WHERE clause is wrong:
# - 168 hours (1 week): 0 messages
# - 720 hours (1 month): 0 messages  
# - 2160 hours (3 months): 0 messages
# - 4320 hours (6 months): 1 message
# - 8760 hours (1 year): 6 messages total
```

### Integer Overflow in Large Time Ranges
```python
# Line causing crashes with large hour values:
seconds_since_apple_epoch = int((hours_ago - apple_epoch).total_seconds())
# Error: "Python int too large to convert to C int"
# Occurs when binding to SQLite with very large numbers
```

### Input Validation Completely Missing
- **Negative Hours**: `-1` hours accepted, produces no error (should reject)
- **Invalid Contact IDs**: `contact:0`, `contact:-1` accepted with misleading errors
- **Overflow Values**: `999999999999` hours crashes instead of validation error
- **No Bounds Checking**: System accepts any input then fails unpredictably

### Error Handling - INCONSISTENT AND MISLEADING
Different error types for similar problems:
- `contact:999` → "No recent contact matches" (misleading - not about recent contacts)
- `contact:1000000` → "Invalid selection" (inconsistent error format)
- Large hours → Integer overflow crash (should be validation error)
- Missing import → NameError crash (should be graceful degradation)

## Performance Considerations

### Database Optimization - BROKEN FOR MESSAGES
- **Contact Queries**: Work efficiently (349 contacts retrieved successfully)
- **Message Queries**: **CATASTROPHICALLY BROKEN** - Return almost no data regardless of time range
- **Connection Management**: Appears to work for contacts, fails for messages
- **Indexing**: Either broken or not used properly for message timestamp queries

### Caching Strategy - IRRELEVANT FOR BROKEN FEATURES
- **Contact Cache**: 5-minute TTL works for contact data
- **Message Cache**: Irrelevant when queries return no data
- **Database Validation**: Works for connection, fails for query logic

### Memory Management - UNTESTED DUE TO NO DATA
- **Streaming Results**: Cannot test when queries return 6 messages from a year
- **Resource Cleanup**: Status unknown
- **Large Dataset Handling**: Definitely broken (crashes on large hour values)

## Architecture Assessment

### Critical System Failures
- **Core SQL Logic**: Completely broken timestamp conversion or WHERE clause
- **Integer Overflow**: No bounds checking causes crashes  
- **Import Management**: Missing critical dependencies
- **Input Validation**: Accepts invalid data then fails
- **Error Recovery**: Crashes instead of graceful degradation

### What Actually Works
- **MCP Protocol**: Server responds to requests
- **Database Connection**: SQLite connections succeed
- **Contact Operations**: AddressBook queries work correctly
- **Basic AppleScript**: Message sending may work (untested with broken contact flow)

### Architectural Recommendation - EMERGENCY REBUILD
The architecture requires **emergency surgery**:

1. **Immediate**: Debug and fix the SQL timestamp logic causing 0 results
2. **Critical**: Add proper input validation and bounds checking  
3. **Essential**: Fix the missing thefuzz import
4. **Mandatory**: Add comprehensive integration testing
5. **Required**: Implement proper error handling instead of crashes

### Root Cause: NO REAL-WORLD TESTING
Evidence of zero actual testing:
- **SQL queries never tested** with real message data
- **Time ranges never validated** against actual timestamps
- **Edge cases never considered** (negative hours, overflow)
- **Integration never tested** end-to-end with real workflows
- **Published broken code** without manual verification

**Conclusion**: This is not an architectural design problem. This is a **complete quality assurance failure** where the basic functionality was never tested before publication.