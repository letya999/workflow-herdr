# AGENTS.md — AI Repo Safety Rules

This repository uses AI Repo Safety guardrails. Follow these rules before coding, committing, pushing, creating public issues/PRs, or reading GitHub context.

## Mandatory workflow

1. Before feature work, ensure `.gitignore`, `.env.example`, `SECURITY.md`, `.dockerignore`, and `.repo-safety/*` exist.
2. Before commit, run `pre-commit run --all-files` or `ai-repo-safety scan --target .`.
3. Before push, run `ai-repo-safety prepush --target .`.
4. Before making the repo public, creating a public issue/PR, or publishing logs, run the release verifier checklist in `assets/agents/release-verifier.md` if available.
5. If any secret is found, stop feature work and follow `docs/incident-cleanup.md`.

## Forbidden files to read, print, summarize, upload, or commit

Do not read or print these files unless the user explicitly confirms the security risk:

- `.env`, `.env.*`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`
- `id_rsa`, `id_ed25519`
- `credentials*.json`, `service-account*.json`
- `token.json`, `tokens.json`, `secrets.json`
- `.mcp.json`, `claude_desktop_config.json`
- `*.ovpn`

## Forbidden actions without explicit confirmation

- `git push`
- making a repository public
- creating public issues or PRs with private context
- uploading logs, screenshots, exports, support tickets, DB dumps, Jira/Confluence exports
- running `env`, `printenv`, `set`, `cat .env`, `type .env`, `Get-Content .env`
- adding or changing MCP servers
- disabling auth, RLS, CORS, input validation, TLS checks, or security scans just to make code work
- installing unknown packages suggested only by model memory

## GitHub context reads

Do not directly use `gh api`, `gh pr view`, `gh issue view`, or raw GitHub web pages for commits, PRs, branches, or issues when the content will enter the AI context.

Use the guard instead:

```bash
ai-repo-safety github-guard read --repo owner/repo --resource pulls --reason "review current PRs"
ai-repo-safety github-guard read --repo owner/repo --resource issues --reason "triage issues"
ai-repo-safety github-guard read --repo owner/repo --resource branches --reason "check branch names"
ai-repo-safety github-guard read --repo owner/repo --resource commits --reason "review recent commits"
```

The guard enforces allowed repos, limits, secret redaction, and prompt-injection detection.

## Dependency policy

Before adding a dependency:

1. Verify the package exists and is maintained.
2. Prefer standard library or already-present dependencies.
3. Run `pip-audit` / `osv-scanner` where applicable.
4. Do not install hallucinated packages.

## Missing tools

If Git, Python, uv, uvx, scanners, or GitHub CLI are missing:

1. Run `ai-repo-safety doctor --agent-plan`.
2. Search official documentation or official releases for the current stable compatible version.
3. Install only from official sources or trusted OS package managers.
4. Re-run `ai-repo-safety doctor`.
