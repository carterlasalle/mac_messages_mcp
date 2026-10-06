# Copyright (c) 2023 Carter Lasalle
"""Command-line interface for Mac Messages MCP.

``mac-messages-cli`` exposes the same local Messages and Contacts data the MCP
server does, but to a human at a terminal: recent messages, fuzzy search,
contacts, group chats, attachments, sending, and access diagnostics.

The public functions in :mod:`mac_messages_mcp.messages` are wrapped with
``bound_untrusted_output`` because their results are model-facing MCP payloads:
newlines and control characters are escaped and the text is fenced inside
``<untrusted-mcp-output>``. A terminal is not a model transcript, so the CLI
unwraps that presentation layer and prints the text as written. The MCP server
keeps the boundary for every model-facing path.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from mac_messages_mcp._version import __version__
from mac_messages_mcp.messages import (
    _check_imessage_availability,
    _describe_attachment,
    _format_phone_for_messages,
    check_addressbook_access,
    check_messages_db_access,
    find_contact_by_name,
    fuzzy_search_messages,
    get_cached_contacts,
    get_recent_messages,
    query_messages_db,
    search_attachments,
    send_message,
)

# Mirrors the server's tool_get_chats query: any chat carrying a display name.
_NAMED_CHATS_QUERY = (
    "SELECT chat_identifier, display_name FROM chat WHERE display_name IS NOT NULL"
)


def _unwrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Return ``fn`` without its ``bound_untrusted_output`` presentation wrapper."""
    return getattr(fn, "__wrapped__", fn)


def _is_error(text: str) -> bool:
    """Return True when a core function reported a failure in its result text."""
    return text.startswith(("Error", "ERROR"))


def _print_result(text: str) -> int:
    """Print a core function result and translate its error prefix into an exit code."""
    print(text)
    return 1 if _is_error(text) else 0


def _cmd_recent(args: argparse.Namespace) -> int:
    return _print_result(
        _unwrap(get_recent_messages)(
            hours=args.hours,
            contact=args.contact,
            chat_id=args.chat,
        )
    )


def _cmd_search(args: argparse.Namespace) -> int:
    return _print_result(
        _unwrap(fuzzy_search_messages)(
            search_term=args.term,
            hours=args.hours,
            threshold=args.threshold,
        )
    )


def _cmd_contact(args: argparse.Namespace) -> int:
    matches = find_contact_by_name(args.name)
    if not matches:
        print(f"No contacts found matching '{args.name}'.")
        return 1
    if len(matches) == 1:
        contact = matches[0]
        print(
            f"Found contact: {contact['name']} ({contact['phone']}) "
            f"with confidence {contact['score']:.2f}"
        )
        return 0
    print(f"Found {len(matches)} contacts matching '{args.name}':")
    for index, contact in enumerate(matches[: args.limit], 1):
        print(
            f"{index}. {contact['name']} ({contact['phone']}) "
            f"- confidence {contact['score']:.2f}"
        )
    if len(matches) > args.limit:
        print(f"...and {len(matches) - args.limit} more.")
    return 0


def _cmd_contacts(args: argparse.Namespace) -> int:
    contacts = get_cached_contacts()
    if not contacts:
        print("No contacts found in AddressBook.")
        return 1
    print(f"Found {len(contacts)} contacts in AddressBook.")
    print(f"Sample entries (first {args.limit}):")
    for number, name in list(contacts.items())[: args.limit]:
        print(f"{_format_phone_for_messages(number) or number} -> {name}")
    return 0


def _cmd_chats(_args: argparse.Namespace) -> int:
    results = query_messages_db(_NAMED_CHATS_QUERY)
    if results and "error" in results[0]:
        print(f"Error accessing chats: {results[0]['error']}")
        return 1
    chats = [row for row in results if row.get("display_name")]
    if not chats:
        print("No named group chats found.")
        return 1
    print("Available group chats:")
    for index, chat in enumerate(chats, 1):
        print(f"{index}. {chat['display_name']} (ID: {chat['chat_identifier']})")
    return 0


def _cmd_attachments(args: argparse.Namespace) -> int:
    return _print_result(
        _unwrap(search_attachments)(
            start_date=args.since,
            end_date=args.until,
            contact=args.contact,
            mime_type=args.mime,
            limit=args.limit,
        )
    )


def _cmd_attachment(args: argparse.Namespace) -> int:
    summary, path = _describe_attachment(args.attachment_id)
    print(summary)
    if path is None:
        return 1
    if args.save:
        destination = Path(args.save).expanduser()
        shutil.copyfile(path, destination)
        print(f"Saved to {destination}")
    return 0


def _cmd_send(args: argparse.Namespace) -> int:
    if not args.yes:
        if not sys.stdin.isatty():
            print(
                "Refusing to send without confirmation: stdin is not a terminal. "
                "Re-run with --yes to send non-interactively.",
                file=sys.stderr,
            )
            return 2
        answer = input(f"Send to {args.recipient}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled; nothing sent.")
            return 1
    return _print_result(
        send_message(
            recipient=args.recipient,
            message=args.message,
            group_chat=args.group,
        )
    )


def _imessage_availability_line(recipient: str, available: bool) -> str:
    """Describe an iMessage availability result the way the MCP tool does."""
    if available:
        return f"{recipient}: iMessage available"
    if any(char.isdigit() for char in recipient):
        return f"{recipient}: no iMessage; messages fall back to SMS/RCS"
    return f"{recipient}: no iMessage; SMS is not available for email addresses"


def _cmd_check(args: argparse.Namespace) -> int:
    exit_code = 0
    for label, check in (
        ("Messages database", check_messages_db_access),
        ("AddressBook", check_addressbook_access),
    ):
        print(f"== {label} ==")
        result = check()
        print(result)
        if _is_error(result):
            exit_code = 1

    if args.recipient:
        print("== iMessage availability ==")
        available = _check_imessage_availability(args.recipient)
        print(_imessage_availability_line(args.recipient, available))
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    """Build the ``mac-messages-cli`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="mac-messages-cli",
        description=(
            "Read, search, send, and diagnose macOS Messages from a terminal. "
            "Requires Full Disk Access and, for sending, Messages automation "
            "permission for the launching terminal."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mac-messages-cli {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    recent = subparsers.add_parser(
        "recent",
        help="Show recent messages, optionally filtered to a contact or group chat.",
    )
    recent.add_argument(
        "-n",
        "--hours",
        type=int,
        default=24,
        help="Hours to look back (default: 24).",
    )
    recent.add_argument(
        "-c",
        "--contact",
        help="Contact name, phone number, email, or 'contact:N' selection.",
    )
    recent.add_argument(
        "--chat",
        metavar="CHAT_ID",
        help="Group chat identifier from 'chats'.",
    )
    recent.set_defaults(handler=_cmd_recent)

    search = subparsers.add_parser(
        "search",
        help="Fuzzy-search message text within a time window.",
    )
    search.add_argument("term", help="Text to fuzzy-match against message bodies.")
    search.add_argument(
        "-n",
        "--hours",
        type=int,
        default=720,
        help="Hours to search backward; 0 means all history (default: 720).",
    )
    search.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=0.6,
        help="Similarity threshold from 0.0 to 1.0 (default: 0.6).",
    )
    search.set_defaults(handler=_cmd_search)

    contact = subparsers.add_parser(
        "contact",
        help="Fuzzy-match a name in Contacts and print send-ready numbers.",
    )
    contact.add_argument("name", help="Contact name or partial name.")
    contact.add_argument(
        "-l",
        "--limit",
        type=int,
        default=10,
        help="Maximum matches to print (default: 10).",
    )
    contact.set_defaults(handler=_cmd_contact)

    contacts = subparsers.add_parser(
        "contacts",
        help="Show the AddressBook contact count and a sample of entries.",
    )
    contacts.add_argument(
        "-l",
        "--limit",
        type=int,
        default=10,
        help="Number of sample entries to print (default: 10).",
    )
    contacts.set_defaults(handler=_cmd_contacts)

    chats = subparsers.add_parser(
        "chats",
        help="List named group chats and their identifiers.",
    )
    chats.set_defaults(handler=_cmd_chats)

    attachments = subparsers.add_parser(
        "attachments",
        help="Search attachment metadata by date range, contact, and MIME type.",
    )
    attachments.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Inclusive start date (UTC).",
    )
    attachments.add_argument(
        "--until",
        metavar="YYYY-MM-DD",
        help="Inclusive end date (UTC).",
    )
    attachments.add_argument(
        "-c",
        "--contact",
        help="Contact name, phone number, or email filter.",
    )
    attachments.add_argument(
        "--mime",
        metavar="TYPE",
        help="MIME type or prefix filter, such as 'image/' or 'application/pdf'.",
    )
    attachments.add_argument(
        "-l",
        "--limit",
        type=int,
        default=50,
        help="Maximum metadata rows to return (default: 50).",
    )
    attachments.set_defaults(handler=_cmd_attachments)

    attachment = subparsers.add_parser(
        "attachment",
        help="Show one attachment's metadata and local path, optionally saving it.",
    )
    attachment.add_argument(
        "attachment_id",
        type=int,
        help="Attachment ROWID from 'attachments' or a message attachment marker.",
    )
    attachment.add_argument(
        "--save",
        metavar="PATH",
        help="Copy the attachment file to this path.",
    )
    attachment.set_defaults(handler=_cmd_attachment)

    send = subparsers.add_parser(
        "send",
        help="Send one message through Messages.app.",
    )
    send.add_argument(
        "recipient",
        help="Phone number, email, contact name, or chat ID with --group.",
    )
    send.add_argument("message", help="Text body to send.")
    send.add_argument(
        "-g",
        "--group",
        action="store_true",
        help="Treat recipient as a group chat ID from 'chats'.",
    )
    send.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Send without the interactive confirmation prompt.",
    )
    send.set_defaults(handler=_cmd_send)

    check = subparsers.add_parser(
        "check",
        help="Diagnose Messages and AddressBook access, optionally iMessage reachability.",
    )
    check.add_argument(
        "-r",
        "--recipient",
        help="Also check iMessage availability for this phone number or email.",
    )
    check.set_defaults(handler=_cmd_check)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as e:  # pragma: no cover - platform/permission failures
        print(f"Error: {e!s}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
