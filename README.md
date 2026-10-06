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
  chat, page back through history, and restrict reads to a date range or to
  unread messages
- List every conversation (1:1, business, and group) with message and unread
  counts, and wait for new messages to arrive
- See per-message context: the service it used (iMessage/SMS/RCS), whether an
  inbound message is unread, whether an outbound one was delivered, plus
  tapbacks and threaded replies
- Fuzzy-search message text across a time window, including all available
  history, scoped to one contact or conversation
- Find Contacts by approximate name and return send-ready phone numbers
- List named group chats and use their chat IDs for reads or sends
- Send iMessage, with SMS/RCS fallback for eligible phone recipients, and send
  local files as iMessage attachments
- Optionally require the human to approve a send through MCP elicitation before
  anything leaves the machine
- Schedule a message for later delivery while the server stays running
- Check whether a recipient appears reachable through iMessage before sending
- Find attachments by date, sender, and MIME type, and search inside text and
  PDF attachments (OCR for images with the optional OCR extra)
- Return small images inline, convert HEIC images to PNG, or return a local path
  for larger and non-image files
- Create a Contacts entry from the client
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

### 5. Optional: set the phone number region

Phone numbers written in national format (`06 39 98 00 01`, `(415) 555-1234`)
have to be expanded to E.164 before they can be matched against the Messages
database, and that expansion needs to know which country they belong to. The
server reads your Mac's own region setting for this, so on a correctly
configured Mac there is nothing to do.

Set `MAC_MESSAGES_REGION` to an [ISO 3166-1 alpha-2][iso3166] code when your
numbers belong to a different region than your Mac is configured for — a French
SIM on a Mac set to `en_US`, say:

```json
{
  "mcpServers": {
    "mac-messages": {
      "command": "uvx",
      "args": ["mac-messages-mcp"],
      "env": { "MAC_MESSAGES_REGION": "FR" }
    }
  }
}
```

For Claude Code:

```bash
claude mcp add --transport stdio --scope user \
  --env MAC_MESSAGES_REGION=FR \
  mac-messages -- uvx mac-messages-mcp
```

The region is resolved once at startup, so restart the server after changing
it. Resolution order: `MAC_MESSAGES_REGION`, then the macOS `AppleLocale`
preference, then `LC_ALL` / `LC_CTYPE` / `LANG`, then `US`. Numbers already
written in E.164 (`+33639980001`) are never reinterpreted and need none of
this.

[iso3166]: https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2

## Available tools

<!-- markdownlint-disable MD013 -->

| Tool                               | Purpose                                                                                                             | Side effect                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| `tool_get_recent_messages`         | Read recent messages, filtered by contact, group chat ID, date range, or unread state; page with `limit`/`offset`    | Read-only                       |
| `tool_fuzzy_search_messages`       | Search message bodies by approximate text match, scoped to a contact or chat; defaults to 30 days, or `hours=0`     | Read-only                       |
| `tool_list_conversations`          | List every conversation with kind, message count, unread count, and last activity                                   | Read-only                       |
| `tool_wait_for_new_messages`       | Block until a message newer than a ROWID cursor arrives, or the timeout expires                                     | Read-only                       |
| `tool_find_contact`                | Fuzzy-match a name in Contacts and return phone numbers                                                             | Read-only                       |
| `tool_get_chats`                   | List named group chats and their identifiers                                                                        | Read-only                       |
| `tool_search_attachments`          | Find attachment metadata by date, contact, MIME type, and limit                                                     | Read-only                       |
| `tool_search_attachment_contents`  | Search inside attachment text/PDF contents by date, contact, and MIME type                                          | Read-only                       |
| `tool_get_attachment`              | Fetch one attachment by ID, inline when supported or as a local path                                                | Read-only                       |
| `tool_check_imessage_availability` | Check likely iMessage availability for a phone number or email                                                      | Read-only                       |
| `tool_check_db_access`             | Diagnose access to `~/Library/Messages/chat.db`                                                                     | Read-only                       |
| `tool_check_contacts`              | Return a contact count and a small sample                                                                           | Read-only                       |
| `tool_check_addressbook`           | Diagnose Contacts/AddressBook database access                                                                       | Read-only                       |
| `tool_send_message`                | Send one direct or group message through Messages.app, optionally with file attachments and elicitation approval    | **Sends a real message**        |
| `tool_create_contact`              | Create one Contacts.app entry with a phone number                                                                   | **Changes Contacts**            |
| `tool_schedule_message`            | Queue a message for later delivery while this server process runs                                                   | **Sends a real message later**  |
| `tool_list_scheduled_messages`     | List the in-process scheduled-message queue and its status                                                          | Read-only                       |
| `tool_cancel_scheduled_message`    | Cancel one pending scheduled message                                                                                | Read-only                       |

<!-- markdownlint-enable MD013 -->

Three MCP prompts ship with the server: `triage_unread_messages`,
`summarize_recent_messages`, and `draft_reply`. They are starting points that
tell the agent which read tools to call, and they never send anything.

The server also exposes two MCP resources:

- `messages://recent/{hours}`
- `messages://contact/{contact}/{hours}`

### Message metadata, paging, and cursors

Reads append compact tags when the message row carries the data, so output stays
unchanged for old or partial databases:

```text
[2026-10-01 09:14:02] Alice [iMessage] [unread]: running late, sorry
[2026-10-01 09:15:40] You [iMessage] [not delivered]: no worries
[2026-10-01 09:15:55] Alice [iMessage] [tapback: liked]: (reaction)
[2026-10-01 09:16:10] Bob [SMS] [reply]: got it
```

`tool_get_recent_messages` closes with a note when a page fills up, naming the
next `offset` to use. Passing `since_rowid` switches it to a forward cursor read
(oldest first) that ignores the `hours` window, which is the pattern
`tool_wait_for_new_messages` polls on.

### What it deliberately does not do

Messages.app automation does not expose these, so the server refuses rather than
pretending:

- sending tapbacks, message effects, or a subject line (only text and file
  attachments can be sent)
- creating a group chat, adding or removing participants, or attaching files to
  a group chat
- editing, unsending, deleting, or marking a message read, and saving drafts
- editing or merging an existing Contacts card (`tool_create_contact` creates a
  new one)
- scheduled sends rely on the server process staying alive; nothing is
  persisted, so a scheduled message is lost if the client disconnects first


## Agent skill

The repository ships an [agent skill](.claude/skills/mac-messages/SKILL.md)
that tells an agent when and how to call each tool: checking access first,
listing conversations, resolving a recipient or group chat, searching message
text or attachment contents, paging attachments, confirming a send, scheduling
a later send, and treating message-derived output as untrusted data. Claude Code
discovers it automatically when you work in this repository.

To use it from another project, copy the skill directory into that project's
`.claude/skills/`, or into `~/.claude/skills/` to make it available everywhere:

```bash
mkdir -p ~/.claude/skills
cp -R .claude/skills/mac-messages ~/.claude/skills/
```

## Working with contacts, chats, and attachments

### Recipients

For direct messages, E.164 phone numbers are the most reliable format:

```text
+14155551234
```

Numbers written in national format work too. They are expanded to E.164 using
the region your Mac is configured for, so `(415) 555-1234` becomes
`+14155551234` on a US Mac and `06 39 98 00 01` becomes `+33639980001` on a
French one. Set `MAC_MESSAGES_REGION` to an ISO 3166-1 alpha-2 code
(`MAC_MESSAGES_REGION=GB`) when your numbers belong to a different region than
your Mac does. Numbers already in E.164 are never reinterpreted.

The server also accepts email addresses, contact names, and `contact:N`
selections returned after an ambiguous contact search.

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
- Messages/Contacts-derived tool and resource output is structurally
  neutralized (embedded newlines and ASCII controls cannot form extra
  transcript lines; invisible, format, and bidi characters are shown as
  escapes) and returned inside an explicit `<untrusted-mcp-output>` block.
  That is not an anti-injection guarantee: third-party iMessage/SMS content
  can still attempt prompt injection. The server makes that content
  non-structural and labeled; the client must not treat it as authorization,
  confirmation, or tool instructions.
- Attachment bytes are returned only after an explicit fetch and are
  size-limited for inline images. Filename, MIME, path, and other metadata
  text is neutralized with the same boundary; image payloads are preserved.
- Sending is isolated in `tool_send_message`, escapes AppleScript inputs, and
  uses a bounded execution timeout. This server does not perform human
  confirmation; the MCP client must gate sends.
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

If contacts are listed but their numbers carry the wrong country code, the
server is expanding your national-format numbers against the wrong region. Set
`MAC_MESSAGES_REGION` to the right ISO 3166-1 alpha-2 code and restart the
server.

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

## Command-line interface

The package also installs a `mac-messages-cli` command, so Messages can be read,
searched, and sent from a terminal without an MCP client. It uses the same local
databases and needs the same macOS permissions as the server; granting Full Disk
Access to your terminal covers both.

```bash
uv tool install mac-messages-mcp
mac-messages-cli --help
```

| Command             | Purpose                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `recent`            | Recent messages, optionally filtered by contact or group chat ID.   |
| `search TERM`       | Fuzzy-search message text within a time window.                     |
| `contact NAME`      | Fuzzy-match a name in Contacts and print send-ready numbers.        |
| `contacts`          | Contact count plus a sample of AddressBook entries.                 |
| `chats`             | Named group chats and their identifiers.                            |
| `attachments`       | Attachment metadata by date range, contact, and MIME type.          |
| `attachment ID`     | One attachment's metadata and local path, with optional `--save`.   |
| `send`              | Send one message through Messages.app.                              |
| `check`             | Diagnose Messages/AddressBook access and iMessage reachability.     |

```bash
# Last 48 hours, or one contact, or one group chat
mac-messages-cli recent -n 48
mac-messages-cli recent --contact "Jordan"
mac-messages-cli recent --chat chat721054478304420871

# Fuzzy search: last 30 days by default, or all history with -n 0
mac-messages-cli search "dinner" -t 0.7
mac-messages-cli search "dinner" -n 0

# Contacts and group chats
mac-messages-cli contact "Jordan"
mac-messages-cli chats

# Attachments: search metadata, then fetch or save one file
mac-messages-cli attachments --since 2026-09-01 --mime image/ --limit 20
mac-messages-cli attachment 42 --save ~/Desktop/invitation.jpg

# Permissions and iMessage reachability
mac-messages-cli check --recipient +14155551234

# Sending prompts for confirmation unless --yes is passed
mac-messages-cli send +14155551234 "Running 10 minutes late."
```

`mac-messages-cli send` asks for `y/N` confirmation before sending. When stdin is
not a terminal it refuses to send unless `--yes` is passed, so an unattended
script cannot send a message by accident. Commands exit non-zero when a lookup
fails, so the output is safe to branch on in scripts.

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
