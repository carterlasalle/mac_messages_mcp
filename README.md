# Mac Messages MCP

A Python bridge for interacting with the macOS Messages app using MCP (Multiple Context Protocol).

## Features

- Read recent messages from the macOS Messages app
- Filter messages by contact
- Send new messages through iMessage
- Access messages via an API

## Requirements

- macOS (tested on macOS 11+)
- Python 3.10+
- Access to the Messages app and its database

## Installation

```bash
# Clone the repository
git clone https://github.com/carterlasalle/mac-messages-mcp.git
cd mac-messages-mcp

# Install dependencies
pip install -e .
```

## Usage

### As a Module

```python
from mac_messages_mcp import get_recent_messages, send_message

# Get recent messages
messages = get_recent_messages(hours=48)
print(messages)

# Send a message
result = send_message(recipient="+1234567890", message="Hello from Mac Messages MCP!")
print(result)
```

### As a Command-Line Tool

```bash
# Run the MCP server
mac-messages-mcp
```

## Development

### Versioning

This project uses semantic versioning. See [VERSIONING.md](VERSIONING.md) for details on how the versioning system works and how to release new versions.

To bump the version:

```bash
python scripts/bump_version.py [patch|minor|major]
```

## Security Notes

This application accesses the Messages database directly, which contains personal communications. Please use it responsibly and ensure you have appropriate permissions.

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 