# Mac Messages MCP

A Python bridge for interacting with the macOS Messages app using MCP (Multiple Context Protocol). 

[![PyPI Downloads](https://static.pepy.tech/badge/mac-messages-mcp)](https://pepy.tech/projects/mac-messages-mcp)

![a-diagram-of-a-mac-computer-with-the-tex_FvvnmbaBTFeKy6F2GMlLqA_IfCBMgJARcia1WTH7FaqwA](https://github.com/user-attachments/assets/dbbdaa14-fadd-434d-a265-9e0c0071c11d)

[![Verified on MseeP](https://mseep.ai/badge.svg)](https://mseep.ai/app/fdc62324-6ac9-44e2-8926-722d1157759a)


<a href="https://glama.ai/mcp/servers/gxvaoc9znc">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/gxvaoc9znc/badge" />
</a>

## Features

- Read recent messages from the macOS Messages app
- Filter messages by contact
- Send new messages through iMessage
- Access messages via an API

## Prerequisites

- macOS (tested on macOS 11+)
- Python 3.10+
- **uv package manager**

### Installing uv

If you're on Mac, install uv using Homebrew:

```bash
brew install uv
```

Otherwise, follow the installation instructions on the [uv website](https://github.com/astral-sh/uv).

⚠️ **Do not proceed before installing uv**

## Installation

### Full Disk Access Permission

⚠️ This application requires **Full Disk Access** permission for your terminal or application to access the Messages database. 

To grant Full Disk Access:
1. Open **System Preferences/Settings** > **Security & Privacy/Privacy** > **Full Disk Access**
2. Click the lock icon to make changes
3. Add your terminal app (Terminal, iTerm2, etc.) or Claude Desktop/Cursor to the list
4. Restart your terminal or application after granting permission

## Integration

### Claude Desktop Integration

1. Go to **Claude** > **Settings** > **Developer** > **Edit Config** > **claude_desktop_config.json**
2. Add the following configuration:

```json
{
    "mcpServers": {
        "messages": {
            "command": "uvx",
            "args": [
                "mac-messages-mcp"
            ]
        }
    }
}
```

### Cursor Integration

Go to **Cursor Settings** > **MCP** and paste this as a command:

```
uvx mac-messages-mcp
```

⚠️ Only run one instance of the MCP server (either on Cursor or Claude Desktop), not both


### Option 1: Install from PyPI

```bash
uv pip install mac-messages-mcp
```

### Option 2: Install from source

```bash
# Clone the repository
git clone https://github.com/carterlasalle/mac_messages_mcp.git
cd mac_messages_mcp

# Install dependencies
uv install -e .
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
# Run the MCP server directly
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

[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/carterlasalle-mac-messages-mcp-badge.png)](https://mseep.ai/app/carterlasalle-mac-messages-mcp)

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 
## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=carterlasalle/mac_messages_mcp&type=Date)](https://www.star-history.com/#carterlasalle/mac_messages_mcp&Date)
