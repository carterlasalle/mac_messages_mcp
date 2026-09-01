# Security Policy

Security fixes are applied to the latest release and the `main` branch.

Report vulnerabilities privately through GitHub's **Security → Report a vulnerability** flow for this repository (private vulnerability reporting is enabled). Include affected versions, reproduction steps, impact, and any suggested remediation. Do not include real message contents, contact records, phone numbers, or attachment files.

The project aims to acknowledge a report within 72 hours and provide an initial severity assessment within seven days.

## Local trust boundary

This server runs with the permissions of the application that launches it. Full Disk Access can expose private local data beyond Messages, so users should grant it only to a trusted MCP client and review that client's tool confirmations and data policies.

## Untrusted Messages and Contacts output

Tool and resource payloads derived from Messages or Contacts are structurally neutralized and returned inside `<untrusted-mcp-output>`. That labeling is not an anti-injection guarantee. Third-party iMessage/SMS/RCS content can still attempt prompt injection; the server makes that content non-structural and explicit so a client can refuse to treat it as authorization, confirmation, or tool instructions. Prompt injection cannot be fully solved inside this server.

`tool_send_message` is a privileged side-effect. This server does not implement client-mediated human approval (the locked `mcp` 1.3.0 FastMCP API has no elicitation/`ctx.elicit` support, and a `confirm=True` argument would be agent-settable). MCP clients must gate sends themselves.
