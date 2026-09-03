# Security Policy

## Supported versions

Security fixes are applied to the latest release and the `main` branch.

| Version | Supported |
| ------- | --------- |
| 1.1.x   | Yes       |
| < 1.1   | Best-effort on `main` only |

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's **Security → Report a vulnerability** flow for this repository (private vulnerability reporting is enabled). That is the coordinated-disclosure channel; do not open a public issue for an unfixed vulnerability.

Include affected versions, reproduction steps, impact, and any suggested remediation. Do not include real message contents, contact records, phone numbers, or attachment files.

The project aims to acknowledge a report within 72 hours and provide an initial severity assessment within seven days. See the [OpenSSF coordinated vulnerability disclosure guide](https://github.com/ossf/oss-vulnerability-guide/blob/main/guide.md) for the process this project follows.

## Local trust boundary

This server runs with the permissions of the application that launches it. Full Disk Access can expose private local data beyond Messages, so users should grant it only to a trusted MCP client and review that client's tool confirmations and data policies.

## Untrusted Messages and Contacts output

Tool and resource payloads derived from Messages or Contacts are structurally neutralized and returned inside `<untrusted-mcp-output>`. That labeling is not an anti-injection guarantee. Third-party iMessage/SMS/RCS content can still attempt prompt injection; the server makes that content non-structural and explicit so a client can refuse to treat it as authorization, confirmation, or tool instructions. Prompt injection cannot be fully solved inside this server.

`tool_send_message` is a privileged side-effect. This server does not implement client-mediated human approval (the locked `mcp` 1.3.0 FastMCP API has no elicitation/`ctx.elicit` support, and a `confirm=True` argument would be agent-settable). MCP clients must gate sends themselves.

## Scorecard checks that cannot be set from this tree

These OpenSSF Scorecard rows are GitHub organization/repository settings or an external badge. Files in this repository cannot enable them, and CI must not fake the badge or protection:

- **Branch-Protection**: a maintainer must enable a `main` ruleset or classic branch protection that blocks force-pushes and deletions, requires a pull request, requires at least one approving review, dismisses stale reviews, and requires status checks. Scorecard's public run also cannot *see* some of those flags without a `SCORECARD_TOKEN` PAT that has Administration:read; the PAT only observes settings, it does not turn protection on.
- **Code-Review**: follows from requiring reviews on `main`. Merging with admin bypass, or committing directly to `main`, keeps this check at zero even when workflows are correct.
- **CII-Best-Practices**: register the project at [OpenSSF Best Practices](https://www.bestpractices.dev/) and complete the passing badge. A workflow cannot mint that badge.
