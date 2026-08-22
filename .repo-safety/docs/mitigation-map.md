# Threat Mitigation Map

| Threat | Risk | Preventive control | Detective control | Corrective control | Status |
|---|---:|---|---|---|---|
| Secret committed to Git | Critical | forbid files, pre-commit, Gitleaks | CI secret scan | rotate + filter history | planned |
| Agent reads `.env` | High | AGENTS.md denylist, hooks | scan logs/context | rotate exposed secret | planned |
| MCP tool poisoning | High | allowlist, pinning, no plaintext tokens | MCP config scanner | remove server, rotate tokens | planned |
| Prompt injection in issue/PR | High | GitHub read guard | prompt-injection scan | discard context, re-run safely | planned |
| Hallucinated dependency | High | dependency policy | pip-audit/OSV | remove package, rotate tokens | planned |
