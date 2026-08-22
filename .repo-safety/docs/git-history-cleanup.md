# Git History Cleanup

Preferred order:

1. Rotate/revoke the secret.
2. Confirm what must be removed.
3. Coordinate with collaborators.
4. Use `git filter-repo` or BFG.
5. Force-push protected branches only after approval.
6. Re-run secret scans.
7. Re-clone repositories if needed.

Example with git-filter-repo:

```bash
git filter-repo --path path/to/secret.file --invert-paths
```

Example with BFG:

```bash
bfg --delete-files .env
```
