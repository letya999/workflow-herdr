# Repository instructions

This repository maintains one portable Agent Skill: `workflow-herdr`. It is a
YAML-defined graph for coordinating a human and AI agents inside Herdr. All
maintained repository content is written in English except `README.ru.md`, the
Russian translation — keep the two in sync.

## Read before editing

Read [SKILL.md](SKILL.md), [workflow.yaml](workflow.yaml),
[references/run.md](references/run.md), and [mappings/README.md](mappings/README.md).

## Preserve the architecture

- Runtime is Herdr sessions, tabs, pane IDs and live agent names — no separate
  runner, daemon, or event bus. Do not add one.
- Python scripts only write files, check invariants, and start seats.
- `workflow.yaml` is the canon (`harnesses`, `nodes`, `graphs`); launch
  arguments live in `mappings/`; project overlays live in `.herdr/workflow.yaml`
  and are deep-merged (dicts merge, lists/scalars replace).
- Keep accepting and normalizing legacy keys `roles` / `volumes` / `clis`.
- `large` requires ≥2 independent workstreams and labeled worktrees; do not
  weaken the guards.

## Validation

Run `python -m unittest discover -s scripts -p "test_*.py" -v` before publishing.

## Safety

- Never commit `.env`, keys, tokens, or service-account JSON.
- `doctor`/`status` are read-only diagnostics — keep them side-effect free.
- See [SECURITY.md](SECURITY.md) for vulnerability reporting.
