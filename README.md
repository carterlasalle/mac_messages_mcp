# Mac Messages MCP

Use Claude, Codex, Cursor, VS Code, or any local MCP client to search, read, and
send messages through the macOS Messages app.

[![PyPI](https://img.shields.io/pypi/v/mac-messages-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/mac-messages-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/mac-messages-mcp?logo=python&logoColor=white)](https://pypi.org/project/mac-messages-mcp/)
[![CI](https://github.com/carterlasalle/mac_messages_mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/carterlasalle/mac_messages_mcp/actions/workflows/ci.yml)
[![Downloads](https://static.pepy.tech/badge/mac-messages-mcp)](https://pepy.tech/project/mac-messages-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Mac Messages MCP runs locally on your Mac. It opens the Messages and Contacts
databases read-only, returns only the data a client asks for, and uses
Messages.app automation only when the client explicitly calls the send tool.

> [!IMPORTANT] This server is macOS-only. Reading messages requires Full Disk
> Access. Sending requires a Mac signed into Messages plus permission for the
> launching app to automate Messages.

## What it can do

- Read recent messages across all conversations or filter by contact or group
  chat
- Fuzzy-search message text across a time window, including all available
  history
- Find Contacts by approximate name and return send-ready phone numbers
- List named group chats and use their chat IDs for reads or sends
- Send iMessage, with SMS/RCS fallback for eligible phone recipients
- Check whether a recipient appears reachable through iMessage before sending
- Find attachments by date, sender, and MIME type
- Return small images inline, convert HEIC images to PNG, or return a local path
  for larger and non-image files
- Diagnose Messages and Contacts database permissions from inside the MCP client

## Quick start

### 1. Install `uv`

```bash
brew install uv
```

Confirm that the launcher is available:

```bash
uvx --version
```

Python 3.10 or newer is required. `uvx` can provision a compatible Python and
installs Mac Messages MCP in an isolated environment, so you do not need to
create a virtual environment first.

### 2. Grant macOS permissions

Open **System Settings → Privacy & Security → Full Disk Access** and enable the
app that will launch the MCP server:

- Claude Desktop, Cursor, VS Code, or the ChatGPT desktop app when configured in
  that app
- Terminal, iTerm2, Ghostty, or another terminal when using Claude Code or Codex
  CLI from that terminal

Quit and reopen the app after changing Full Disk Access. On the first contact
lookup or send, macOS may separately ask for access to Contacts or permission to
control Messages. Allow those prompts.

Also make sure Messages.app is open, signed in, and already able to send a
normal message.

### 3. Add the server to your MCP client

The server command is the same everywhere:

```text
uvx mac-messages-mcp
```

Choose your client below.

#### Claude Desktop

Open **Claude → Settings → Developer → Edit Config**, then add:

```json
{
  "mcpServers": {
    "mac-messages": {
      "command": "uvx",
      "args": ["mac-messages-mcp"]
    }
  }
}
```

Preserve any other servers already in `claude_desktop_config.json`, save the
file, and restart Claude Desktop.

Claude Desktop also supports installable `.mcpb` extensions. See
[Build the Claude Desktop extension](#build-the-claude-desktop-extension) if you
want to package this repository as one.

#### Claude Code

Add it once at user scope so it is available in every project:

```bash
claude mcp add --transport stdio --scope user mac-messages -- uvx mac-messages-mcp
```

Verify it:

```bash
claude mcp get mac-messages
```

Inside Claude Code, run `/mcp` to inspect the connection and tools.

#### Codex CLI, Codex IDE extension, and ChatGPT desktop app

Codex clients on the same Mac share MCP configuration. Add the server with:

```bash
codex mcp add mac-messages -- uvx mac-messages-mcp
```

Then verify it:

```bash
codex mcp list
```

You can also add it directly to `~/.codex/config.toml`:

```toml
[mcp_servers.mac-messages]
command = "uvx"
args = ["mac-messages-mcp"]
```

Restart the desktop app or IDE extension after changing the configuration. In
Codex CLI, use `/mcp` to view the active server.

#### Cursor

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-light.svg)](https://cursor.com/install-mcp?name=mac-messages-mcp&config=eyJjb21tYW5kIjoidXZ4IG1hYy1tZXNzYWdlcy1tY3AifQ%3D%3D)

Or open **Cursor Settings → Tools & MCP → New MCP Server** and use:

```json
{
  "mcpServers": {
    "mac-messages": {
      "command": "uvx",
      "args": ["mac-messages-mcp"]
    }
  }
}
```

Restart the server from Cursor's MCP settings after saving.

#### VS Code / GitHub Copilot

Open the Command Palette and run **MCP: Add Server**. Choose **Command
(stdio)**, enter `uvx` as the command, add `mac-messages-mcp` as the argument,
and install it globally.

Or add it from a terminal:

```bash
code --add-mcp '{"name":"mac-messages","command":"uvx","args":["mac-messages-mcp"]}'
```

The equivalent user or workspace `mcp.json` entry is:

```json
{
  "servers": {
    "mac-messages": {
      "type": "stdio",
      "command": "uvx",
      "args": ["mac-messages-mcp"]
    }
  }
}
```

> [!NOTE] VS Code uses a top-level `servers` object. Claude Desktop and Cursor
> use `mcpServers`.

#### Other stdio MCP clients

Use this generic server definition:

```json
{
  "command": "uvx",
  "args": ["mac-messages-mcp"]
}
```

If a GUI client reports that `uvx` cannot be found, run `which uvx` in Terminal
and replace `"uvx"` with the returned absolute path. Homebrew commonly installs
it at `/opt/homebrew/bin/uvx` on Apple silicon and `/usr/local/bin/uvx` on Intel
Macs.

### 4. Verify the connection

Ask your client to call `tool_check_db_access`, then `tool_check_addressbook`.
Once both succeed, try prompts such as:

```text
Show me my messages from the last two hours.
```

```text
Find messages from Carter about dinner in the last 30 days.
```

```text
Find PDFs sent to me this month, but do not open any yet.
```

```text
Find Jordan in my contacts and draft a message saying I am running 10 minutes
late. Do not send it until I confirm.
```

The first `uvx` launch can take longer while it downloads and caches Python
dependencies.

## Available tools

<!-- markdownlint-disable MD013 -->

| Tool                               | Purpose                                                                                                | Side effect              |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------ |
| `tool_get_recent_messages`         | Read recent messages, optionally filtered by contact or group chat ID                                  | Read-only                |
| `tool_fuzzy_search_messages`       | Search message bodies by approximate text match; defaults to 30 days, or use `hours=0` for all history | Read-only                |
| `tool_find_contact`                | Fuzzy-match a name in Contacts and return phone numbers                                                | Read-only                |
| `tool_get_chats`                   | List named group chats and their identifiers                                                           | Read-only                |
| `tool_search_attachments`          | Find attachment metadata by date, contact, MIME type, and limit                                        | Read-only                |
| `tool_get_attachment`              | Fetch one attachment by ID, inline when supported or as a local path                                   | Read-only                |
| `tool_check_imessage_availability` | Check likely iMessage availability for a phone number or email                                         | Read-only                |
| `tool_check_db_access`             | Diagnose access to `~/Library/Messages/chat.db`                                                        | Read-only                |
| `tool_check_contacts`              | Return a contact count and a small sample                                                              | Read-only                |
| `tool_check_addressbook`           | Diagnose Contacts/AddressBook database access                                                          | Read-only                |
| `tool_send_message`                | Send one direct or group message through Messages.app                                                  | **Sends a real message** |

<!-- markdownlint-enable MD013 -->

The server also exposes two MCP resources:

- `messages://recent/{hours}`
- `messages://contact/{contact}/{hours}`

## Working with contacts, chats, and attachments

### Recipients

For direct messages, E.164 phone numbers are the most reliable format:

```text
+14155551234
```

The server normalizes bare numbers with a country code and converts 10-digit US
numbers to `+1...`. It also accepts email addresses, contact names, and
`contact:N` selections returned after an ambiguous contact search.

For a group conversation, call `tool_get_chats`, pass its chat ID to
`tool_send_message`, and set `group_chat=true`. Use the same ID as `chat_id` in
`tool_get_recent_messages` to read that conversation.

### Attachments

Attachment access is deliberately split into three steps:

1. Message reads and searches add compact markers such as
   `[attachments: #42 image/jpeg (invitation.jpg)]`.
2. `tool_search_attachments` searches metadata without loading file contents.
3. `tool_get_attachment` fetches one selected attachment.

Images up to 5 MB are returned inline by default. HEIC images are converted to
PNG. Larger images, PDFs, video, and audio are returned as local filesystem
paths so the MCP client can decide whether to open them. Stickers, link-preview
payloads, and `.pluginPayloadAttachment` containers are filtered out.

## Privacy and security

- Messages and Contacts SQLite connections use read-only mode and SQLite
  `query_only`.
- The server does not upload, mirror, index, or maintain its own message
  archive.
- Results are written to the local MCP stdio connection started by your client.
- Message bodies are sanitized and bounded before being returned.
- Attachment bytes are returned only after an explicit fetch and are
  size-limited for inline images.
- Sending is isolated in `tool_send_message`, escapes AppleScript inputs, and
  uses a bounded execution timeout.
- Full Disk Access is broader than Messages access. Grant it only to MCP clients
  you trust and review the destination before approving a send.

See [SECURITY.md](SECURITY.md) to report a vulnerability privately.

## Troubleshooting

### `uvx` or `spawn uvx ENOENT`

The GUI app cannot see your shell's Homebrew path. Run:

```bash
which uvx
```

Use that full path as the MCP `command`, then restart the client.

### `Operation not permitted`, `unable to open database file`, or no messages

Grant Full Disk Access to the app that launches the server, not just to
Messages.app. Completely quit and reopen the launcher afterward, then call
`tool_check_db_access` again.

For Claude Code or Codex CLI, the launcher is normally your terminal. For a
desktop or IDE integration, it is normally Claude Desktop, Cursor, VS Code, or
the ChatGPT desktop app itself.

### Contacts are empty or contact lookup fails

Allow the launching app to access Contacts if macOS prompts. Confirm Full Disk
Access, restart the app, and call `tool_check_addressbook` followed by
`tool_check_contacts`.

### Reading works but sending fails

1. Open Messages.app and send a message manually to confirm the account and
   recipient work.
2. Check **System Settings → Privacy & Security → Automation** and allow the
   launching app to control Messages.
3. Prefer an E.164 number such as `+14155551234` for a direct recipient.
4. Use `tool_check_imessage_availability` to inspect the likely route.

### An attachment is listed but cannot be opened

Messages may retain database metadata after macOS has offloaded the file. Open
the conversation in Messages.app and download the attachment, then retry
`tool_get_attachment`.

### The server appears to hang when run in Terminal

That is normal for an MCP stdio server: it waits for protocol input from a
client. Use your client's MCP status view, or launch the MCP Inspector:

```bash
yarn dlx @modelcontextprotocol/inspector uvx mac-messages-mcp
```

## Install as a standalone tool

MCP clients can launch the package directly with `uvx`; a permanent installation
is optional.

```bash
uv tool install mac-messages-mcp
mac-messages-mcp
```

Upgrade or remove it with:

```bash
uv tool upgrade mac-messages-mcp
uv tool uninstall mac-messages-mcp
```

## Python API

The MCP server is the primary interface, but the package also exports its core
read/send functions:

```python
from mac_messages_mcp import get_recent_messages, send_message

recent = get_recent_messages(hours=48)
print(recent)

result = send_message(
    recipient="+14155551234",
    message="Hello from Mac Messages MCP!",
)
print(result)
```

These calls use the same macOS permissions and can send real messages.

## Development

```bash
git clone https://github.com/carterlasalle/mac_messages_mcp.git
cd mac_messages_mcp

uv sync --frozen --extra dev
uv run pytest
uv run black --check .
uv run isort --check-only .
uv build
```

Tests mock AppleScript and use temporary database fixtures; they must never read
a contributor's real Messages or Contacts data. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the contribution checklist and
[VERSIONING.md](VERSIONING.md) for releases.

### Build the Claude Desktop extension

The repository includes an MCPB `manifest.json` and a build script that can
bundle an architecture-specific `uv` binary:

```bash
yarn global add @anthropic-ai/mcpb
uv run python scripts/build_mcpb.py
```

For an Intel build:

```bash
uv run python scripts/build_mcpb.py --arch x86_64
```

Install the generated `.mcpb` from **Claude Desktop → Settings → Extensions →
Advanced settings → Install Extension…**. A bundled extension still needs
network access on first launch to download Python and the package dependencies.

Use `--no-bundle` to package against the system `uv`, or run
`uv run python scripts/build_mcpb.py --help` for every option.

## Docker

The included Dockerfile is for package and catalog validation. A Linux container
cannot access macOS TCC permissions or automate Messages.app, so Docker is not a
supported way to read or send messages on the host Mac.

## License

[MIT](LICENSE) © Carter Lasalle

## Contributing

Issues and focused pull requests are welcome. Do not include real message
contents, contacts, phone numbers, database files, or attachments in bug reports
or fixtures.

[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) ·
[Security](SECURITY.md) · [PyPI](https://pypi.org/project/mac-messages-mcp/)
