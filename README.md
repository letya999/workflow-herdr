# Workflow Herdr

<p align="center">
  <a href="README.ru.md">Русский</a> · <strong>English</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://skills.sh/letya999/workflow-herdr"><img src="https://skills.sh/b/letya999/workflow-herdr" alt="skills.sh"></a>
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
</p>

A YAML-defined graph for coordinating a human and AI agents **inside Herdr**.

Runtime is sessions, tabs, pane IDs and live agent names. Python scripts write
files, check invariants and start seats. No separate runner, daemon or event bus.

## What's inside

- `small`, `medium`, `large` graphs (plus any overlay graph composed of YAML nodes);
- `Brain`, `Orchestrator`, `Dispatcher`, `Worker` node roles;
- state layers: Herdr product state, global index, project overlay, run
  (`identity`, `run.json`, `orchestration`, `artifacts`, `tasks`);
- preflight for CLI / kind / model / effort / usage before any topology;
- `doctor` and `status` (mapped / orphan);
- focus-or-start with `agent_pane_busy` / `agent_prompt_stalled` retry and rollback;
- medium runs in the current workspace (tab/pane rename), large uses labeled
  worktrees;
- BODW loop: Dispatcher drives Workers via `prompt --wait`, Brain does not wait.

## Install

With `npx skills`:

```bash
npx skills add letya999/workflow-herdr
```

Or clone into an agent skill directory:

```powershell
git clone https://github.com/letya999/workflow-herdr.git "$env:USERPROFILE\.codex\skills\workflow-herdr"
```

Copy the same directory into `$env:USERPROFILE\.agents\skills\workflow-herdr` and
`$env:USERPROFILE\.grok\skills\workflow-herdr` if you use those harnesses too.

## Quick start

### Requirements

- Python 3.10+
- Git
- Herdr installed
- CLIs from `workflow.yaml`: Codex (Orchestrator) and Devin (Dispatcher/Worker)

### Check a project

```powershell
python scripts/bootstrap.py --project "C:\path\to\project"
```

Returns JSON with an `ok` field.

### Run a workflow

Short task: Brain hands the intent to a single Worker in the current tab, no
`--wait` on the Brain side.

For a planned task:

```powershell
python scripts/bootstrap.py --project "C:\path\to\project"
python scripts/init_work.py --project "C:\path\to\project" --change add-login --volume medium
python scripts/layout_graph.py --project "C:\path\to\project" --change add-login --volume medium
python scripts/prompt_seat.py --project "C:\path\to\project" --change add-login --seat orchestrator --from brain --text "intent"
python scripts/orchestrate.py --project "C:\path\to\project" --change add-login --from brain --on goal_created
python scripts/task_state.py --project "C:\path\to\project" --change add-login --dump
```

`large` requires at least two independent workstreams with non-overlapping
files and one labeled worktree per stream.

## Configuration

The canon is [`workflow.yaml`](workflow.yaml): `harnesses`, `nodes`, `graphs`.
Launch arguments live in [`mappings/`](mappings/): one YAML/JSON per harness,
with optional per-model overrides. A local `.herdr/workflow.yaml` manifest is
deep-merged: dicts are merged, lists and scalars replaced. Legacy keys `roles` /
`volumes` / `clis` are still accepted and normalized.

Minimal overlay:

```yaml
nodes:
  worker:
    harness: grok
    model: grok-4.6
    effort: high
guards:
  large_min_runnable_tasks: 3
```

Template: [`assets/workflow.example.yaml`](assets/workflow.example.yaml).
Argument format: [`mappings/README.md`](mappings/README.md).
Project profile: [`references/project-workflow.md`](references/project-workflow.md).
Running the loop: [`references/run.md`](references/run.md).

Main task transitions:

```text
pending → ready → assigned → running → in_review → accepted → closed
```

`blocked` stops until a fact or a human decision.

## Testing

```powershell
python -m unittest discover -s scripts -p "test_*.py" -v
```

## Structure

```text
workflow.yaml                 # harnesses, nodes, graphs, guards
SKILL.md                      # skill for the harness
README.md                     # quickstart (English)
README.ru.md                  # quickstart (Russian)
scripts/                      # file helpers, start_seat, tests
assets/                       # run-file templates
references/run.md             # launch contract and BODW loop
```

## Security

Do not commit `.env` files, keys, tokens, or service-account JSON. Vulnerability
reporting: [`SECURITY.md`](SECURITY.md).

## Contributing

`feature branch → dev → main`. Details in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

[MIT](LICENSE).
