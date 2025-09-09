# Mac Messages MCP

A Python bridge for interacting with the macOS Messages app using MCP (Multiple Context Protocol). 

[![PyPI Downloads](https://static.pepy.tech/badge/mac-messages-mcp)](https://pepy.tech/projects/mac-messages-mcp)

[![Trust Score](https://archestra.ai/mcp-catalog/api/badge/quality/carterlasalle/mac_messages_mcp)](https://archestra.ai/mcp-catalog/carterlasalle__mac_messages_mcp)

![a-diagram-of-a-mac-computer-with-the-tex_FvvnmbaBTFeKy6F2GMlLqA_IfCBMgJARcia1WTH7FaqwA](https://github.com/user-attachments/assets/dbbdaa14-fadd-434d-a265-9e0c0071c11d)

[![Verified on MseeP](https://mseep.ai/badge.svg)](https://mseep.ai/app/fdc62324-6ac9-44e2-8926-722d1157759a)


<a href="https://glama.ai/mcp/servers/gxvaoc9znc">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/gxvaoc9znc/badge" />
</a>

## Quick Install

### For Cursor Users

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-light.svg)](https://cursor.com/install-mcp?name=mac-messages-mcp&config=eyJjb21tYW5kIjoidXZ4IG1hYy1tZXNzYWdlcy1tY3AifQ%3D%3D)

*Click the button above to automatically add Mac Messages MCP to Cursor*

### For Claude Desktop Users

See the [Integration section](#integration) below for setup instructions.

## Features

- **Universal Message Sending**: Automatically sends via iMessage or SMS/RCS based on recipient availability
- **Smart Fallback**: Seamless fallback to SMS when iMessage is unavailable (perfect for Android users)
- **Message Reading**: Read recent messages from the macOS Messages app
- **Contact Filtering**: Filter messages by specific contacts or phone numbers
- **Fuzzy Search**: Search through message content with intelligent matching
- **iMessage Detection**: Check if recipients have iMessage before sending
- **Cross-Platform**: Works with both iPhone/Mac users (iMessage) and Android users (SMS/RCS)

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

#### Option 1: One-Click Install (Recommended)

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-light.svg)](https://cursor.com/install-mcp?name=mac-messages-mcp&config=eyJjb21tYW5kIjoidXZ4IG1hYy1tZXNzYWdlcy1tY3AifQ%3D%3D)

#### Option 2: Manual Setup

Go to **Cursor Settings** > **MCP** and paste this as a command:

```
uvx mac-messages-mcp
```

⚠️ Only run one instance of the MCP server (either on Cursor or Claude Desktop), not both

### Docker Container Integration

If you need to connect to `mac-messages-mcp` from a Docker container, you'll need to use the `mcp-proxy` package to bridge the stdio-based server to HTTP.

#### Setup Instructions

1. **Install mcp-proxy on your macOS host:**
```bash
npm install -g mcp-proxy
```

2. **Start the proxy server:**
```bash
# Using the published version
npx mcp-proxy uvx mac-messages-mcp --port 8000 --host 0.0.0.0

# Or using local development (if you encounter issues)
npx mcp-proxy uv run python -m mac_messages_mcp.server --port 8000 --host 0.0.0.0
```

3. **Connect from Docker:**
Your Docker container can now connect to:
- URL: `http://host.docker.internal:8000/mcp` (on macOS/Windows)
- URL: `http://<host-ip>:8000/mcp` (on Linux)

4. **Docker Compose example:**
```yaml
version: '3.8'
services:
  your-app:
    image: your-image
    environment:
      MCP_MESSAGES_URL: "http://host.docker.internal:8000/mcp"
    extra_hosts:
      - "host.docker.internal:host-gateway"  # For Linux hosts
```

5. **Running multiple MCP servers:**
```bash
# Terminal 1 - Messages MCP on port 8001
npx mcp-proxy uvx mac-messages-mcp --port 8001 --host 0.0.0.0

# Terminal 2 - Another MCP server on port 8002
npx mcp-proxy uvx another-mcp-server --port 8002 --host 0.0.0.0
```

**Note:** Binding to `0.0.0.0` exposes the service to all network interfaces. In production, consider using more restrictive host bindings and adding authentication.


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

### Smart Message Delivery

Mac Messages MCP automatically handles message delivery across different platforms:

- **iMessage Users** (iPhone, iPad, Mac): Messages sent via iMessage
- **Android Users**: Messages automatically fall back to SMS/RCS
- **Mixed Groups**: Optimal delivery method chosen per recipient

```python
# Send to iPhone user - uses iMessage
send_message("+1234567890", "Hey! This goes via iMessage")

# Send to Android user - automatically uses SMS
send_message("+1987654321", "Hey! This goes via SMS") 

# Check delivery method before sending
check_imessage_availability("+1234567890")  # Returns availability status
```

### As a Module

```python
from mac_messages_mcp import get_recent_messages, send_message

# Get recent messages
messages = get_recent_messages(hours=48)
print(messages)

# Send a message (automatically chooses iMessage or SMS)
result = send_message(recipient="+1234567890", message="Hello from Mac Messages MCP!")
print(result)  # Shows whether sent via iMessage or SMS
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
