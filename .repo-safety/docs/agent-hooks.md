# Agent Hook MVP

This project can install a minimal project-local hook layer for the
major AI coding CLIs that currently expose official hook or plugin
surfaces:

- Codex
- Claude Code
- OpenCode
- Antigravity CLI

## Scope

The MVP is intentionally small, but the default gate is a single
preflight profile rather than one scanner at a time. It behaves as
follows:

1. always run `gitleaks`
2. always run `trufflehog`
3. run `opengrep` when `.repo-safety/opengrep/` exists
4. run `bandit` when the repo looks like a Python project

For `Codex` and `Claude Code`, the generated project hooks also add
an MCP invocation audit for `mcp__github__.*` and `mcp__gitlab__.*`.
Those hooks:

1. append JSONL audit records to `.repo-safety/logs/mcp-audit.jsonl`
2. allow read-style tools
3. block write-capable GitHub/GitLab MCP tools by default unless the
   repo explicitly allowlists them in `.repo-safety/config.json`

The generated hooks run **only** before sensitive commands such as:

- `git commit`
- `git push`
- `git tag`
- `gh pr create`
- `npm publish`
- `uv publish`
- `twine upload`

If the pending command is not in this class, the hook exits quickly
without running scanners.

## Install

```bash
ai-repo-safety install-agent-hooks --target . --tool all
```

Or limit installation to one runtime:

```bash
ai-repo-safety install-agent-hooks --target . --tool codex
ai-repo-safety install-agent-hooks --target . --tool claude
ai-repo-safety install-agent-hooks --target . --tool opencode
ai-repo-safety install-agent-hooks --target . --tool antigravity
```

## Generated files

```text
.repo-safety/scripts/agent_hook_runner.py
docs/agent-hooks.md
.codex/hooks.json
.claude/settings.json
.opencode/plugins/ai-repo-safety.js
.agents/hooks.json
```

## Runtime Matrix

| Runtime | Project-local entrypoint | How it is discovered | Activation notes |
| --- | --- | --- | --- |
| Codex | `.codex/hooks.json` | Codex reads project hooks from the repo `.codex/` layer alongside user/system layers | The project layer must be trusted; review via `/hooks` if Codex marks the hook as untrusted. The generated config includes `commandWindows` overrides for Windows and separate GitHub/GitLab MCP matcher groups |
| Claude Code | `.claude/settings.json` | Claude Code reads hooks under the `hooks` key from project settings | If the session is already open, reload or restart the session after changing the file. This runtime gets shell preflight plus MCP GitHub/GitLab audit |
| OpenCode | `.opencode/plugins/ai-repo-safety.js` | OpenCode auto-loads project plugins from `.opencode/plugins/` at startup | Restart or reload OpenCode if the project was already open before generation |
| Antigravity | `.agents/hooks.json` | Antigravity uses workspace/project customization under `.agents/` | Restart or reload the workspace so the runtime re-reads the workspace hook config. The generated config includes a Windows-specific command override |

## Project Scope

These hooks are intentionally **project-local**, not global:

- they travel with the repository
- they express repository policy rather than user preference
- different repositories can enforce different safety levels
- the same user can still keep stricter global hooks outside the repo

## Design notes

- The hook logic is centralized in `.repo-safety/scripts/agent_hook_runner.py`.
- The runner uses only the Python standard library so it can execute
  inside the local project without importing `ai_repo_safety`.
- `gitleaks` is mandatory in the preflight profile because a repo
  safety gate should not allow sensitive push/publish flows when the
  primary secret scanner is unavailable.
- `OpenCode` uses a small plugin wrapper because its extensibility
  surface is event-driven JavaScript rather than a standalone
  `hooks.json` file.
- `Codex`, `Claude Code`, and `Antigravity` use project-local config
  files that trigger a shell-command hook before sensitive commands.
- `Codex` and `Antigravity` emit `commandWindows` overrides so the
  generated hook stays usable on Windows without depending on shell
  path translation.
- The current MCP audit is intentionally narrower than the shell
  gate: it focuses on GitHub/GitLab MCP tools where delegated API
  actions are most likely to mutate external systems silently.

## MCP Policy

Optional repository policy in `.repo-safety/config.json`:

```json
{
  "mcp_policy": {
    "audit_log": ".repo-safety/logs/mcp-audit.jsonl",
    "allow_write_tools": [
      "mcp__gitlab__create_merge_request_note"
    ]
  }
}
```

- `audit_log`: overrides the default JSONL path
- `allow_write_tools`: regex patterns matched with `re.fullmatch`
  against the MCP tool name

## Limits

- This is a **minimal** gate, not a complete enforcement boundary.
- It covers shell-style sensitive operations, not every possible edit
  or network path.
- `gitleaks` and `trufflehog` are always part of the profile.
- `bandit` runs only when the repository looks like a Python project.
- `opengrep` runs only when the generated rules directory exists.
- `trufflehog` uses `git --since-commit` when possible and falls back
  to filesystem scanning on short or detached history.
