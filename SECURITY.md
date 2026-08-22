# Security Policy

## Reporting a vulnerability

Use a private GitHub security advisory. Do not open a public issue containing
credentials, exploit details, private logs, user data, or infrastructure data.

If a secret is exposed, revoke or rotate it first, then clean Git history.

## Local checks

This repository uses pre-commit and pre-push checks for sensitive files, MCP
configuration, secret scanning, static analysis, and dependency auditing.
