# MCP Safety Policy

Treat MCP servers as supply-chain dependencies and local execution surfaces.

Rules:

1. Use allowlist only.
2. Pin MCP server versions or commit SHAs where possible.
3. Prefer OAuth or short-lived credentials over long-lived static tokens.
4. Do not store plaintext tokens in `.mcp.json`.
5. If a token must exist locally, pair it with explicit expiry/rotation metadata and keep it out of git.
6. Do not grant write, delete, admin, or wildcard scopes by default.
7. Prefer read-only tools and split servers by task boundary.
8. Do not commit `.mcp.json` or `claude_desktop_config.json`.
9. Do not allow new STDIO MCP servers without review.
10. Do not auto-install MCP servers from untrusted sources.
11. Pin package runners and images:
   - `npx package@version`
   - `uvx package==version`
   - pinned container image tags or digests
12. Require tool-call audit logging or equivalent session logs for sensitive MCP operations.
13. Do not give one agent access to GitHub, filesystem, database, Jira, and shell unless necessary.
14. Use one repo / one task / one scope per session.
15. Review tool descriptions for prompt injection.
16. Never let MCP tools read `.env`, private keys, credential files, or support/user exports.

Run:

```bash
python .repo-safety/scripts/scan_mcp_config.py
```
