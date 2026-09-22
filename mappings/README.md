# Harness argument mappings

`workflow.yaml` points to this folder through `command_mappings`. One file is
loaded per harness: `codex.yaml`, `grok.yaml`, or `devin.yaml`. JSON files are
also accepted.

The top-level `args` list is the default. Tokens are expanded at launch:

- `{model}` — node model;
- `{effort}` — node effort;
- `{n}` — seat instance number;
- `{change}` — change name.

If one model needs different arguments, add a model override:

```yaml
args:
  - "--model"
  - "{model}"
models:
  model-id:
    args:
      - "--special-flag"
      - "{model}"
```

Missing mapping files fall back to legacy `harness.args` / `clis.*.native_args`.
Project manifests can set `command_mappings` to a project-local directory or
set `harnesses.<name>.mapping` to one explicit YAML/JSON file.
