# Contributing

## Branch flow

Use `feature branch -> dev -> main`:

1. Branch from `dev` using `feature/<name>`, `fix/<name>`, or `codex/<name>`.
2. Open a pull request into `dev`.
3. Run tests and security checks before merge.
4. Merge tested releases from `dev` into `main` only.

Do not push feature commits directly to `dev` or `main`.

## Local checks

```powershell
python -m unittest discover -s scripts -p "test_*.py" -v
pre-commit run --all-files
```

Keep changes focused. Update `SKILL.md`, `README.md`, examples, and tests when
behavior or configuration changes.
