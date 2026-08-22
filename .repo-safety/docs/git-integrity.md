# Git Integrity Audit

`ai-repo-safety git-integrity --target .` is a lightweight local
audit, not a cryptographic proof that history was never rewritten.

It is designed to surface warnings before release or before trusting
recent history in an agent-heavy workflow.

## What it checks

1. whether the current branch has an upstream
2. whether local history diverged from upstream
3. whether recent reflog entries include rewrite-style operations
   such as rebase, reset, amend, or force-push-like updates
4. whether `HEAD` is locally verifiable as a signed commit
5. whether the latest reachable tag is locally verifiable as signed

## What it does not prove

- It cannot prove that a remote never accepted a force push.
- It cannot prove that every commit in history is authentic.
- It cannot replace branch protection, signed tags, or CODEOWNERS.

## Blame / Attribution

When the command reports warnings, it also prints audit commands:

```bash
git log --show-signature --decorate -n 20
git blame <path>
git range-diff @{upstream}...HEAD
git log --follow -- <path>
```

Use these to inspect who changed a file, whether a commit is signed,
and whether a branch was reshaped after review.
