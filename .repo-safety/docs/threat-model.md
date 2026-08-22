# Threat Model

## System overview

Describe the system, main users, deployment model, and external integrations.

## Assets

| Asset | Sensitivity | Notes |
|---|---|---|
| Secrets / API tokens | High | Must not enter Git, prompts, issues, logs |
| User data / PII | High | Use synthetic data in repo |
| GitHub context | Medium/High | Issues/PRs may contain prompt injection or secrets |
| MCP configs | High | Can contain tokens and local execution commands |

## Trust boundaries

- Developer workstation ↔ AI agent
- AI agent ↔ filesystem
- AI agent ↔ GitHub
- AI agent ↔ MCP tools
- Local repo ↔ public GitHub
- Application ↔ external APIs

## STRIDE-lite

| Category | Question | Current answer | Mitigation |
|---|---|---|---|
| Spoofing | Can attacker impersonate a user/tool? | TBD | Strong auth, scoped tokens |
| Tampering | Can data/config be modified? | TBD | protected branches, review, validation |
| Repudiation | Can actions be denied? | TBD | audit logs, Git history, CI logs |
| Information Disclosure | Can secrets/PII leak? | TBD | secret scanning, redaction, env-only config |
| Denial of Service | Can resources be exhausted? | TBD | rate limits, quotas |
| Elevation of Privilege | Can agent/tool gain extra power? | TBD | least privilege, MCP allowlist |

## Top risks

| Risk | Impact | Likelihood | Owner | Status |
|---|---:|---:|---|---|
| Secret committed to Git | Critical | Medium | TBD | Open |
| Agent reads `.env` into context | High | Medium | TBD | Open |
| Malicious GitHub issue prompt injection | High | Medium | TBD | Open |

## Security requirements

- Real secrets must never be committed.
- GitHub issue/PR/commit reads must go through `github-guard` when entering AI context.
- MCP configs must not be committed and must not contain plaintext credentials.
- Public repo release requires `ai-repo-safety scan` and release verification.
