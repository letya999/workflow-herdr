# Secret Leak Cleanup

If a secret was committed, printed, pasted into an issue, sent to an agent, or otherwise exposed:

1. Stop feature work.
2. Revoke or rotate the exposed secret first.
3. Identify the exposed secret type, owner, scope, TTL, and blast radius.
4. Search for exposure in:
   - working tree
   - Git history
   - branches
   - tags
   - forks
   - CI logs
   - issues / PRs
   - releases
   - agent logs
   - MCP configs
5. Add file patterns to `.gitignore` and `.repo-safety/config.json`.
6. Remove from Git index if currently tracked:
   `git rm --cached path/to/file`
7. Rewrite history only after coordination:
   - `git filter-repo`
   - BFG Repo-Cleaner
8. Force-push only after approval.
9. Ask contributors to re-clone or clean local history.
10. Run Gitleaks and TruffleHog again.
11. Document incident timeline and actions.

Do not rely on deleting a file from the latest commit. Secrets in history are still exposed.
