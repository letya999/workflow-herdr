---
name: workflow-herdr
description: >
  Start a Herdr work run for a change. Use when starting work, doing a
  task in Herdr, splitting work across panes, or chatting from a Herdr
  terminal - even if they just say do this. Do NOT use for a solo one-pane
  edit, headless delegates, or product job queues.
---

# Workflow Herdr

This is **not** the `herdr` skill. `herdr` is the multiplexer. This skill is
the workflow overlay: doctor, detection, graph, layout.

Python scripts do not loop `herdr agent prompt`. Herdr is the runtime.

- How to run: [references/run.md](references/run.md)
- Config: [workflow.yaml](workflow.yaml)
- Project profile: [references/project-workflow.md](references/project-workflow.md)

## Do

If `HERDR_ENV` is not `1`, stop.

Brain is this chat. Intent is what the human typed here.

**1. Doctor first** — before sizing, before any pane/tab/workspace:

```text
python scripts/bootstrap.py --project <abs>
# or: python scripts/bootstrap.py --project <abs> --fresh
```

That resolves `.herdr/workflow.yaml` over the global default, then live-checks
every startable seat: Herdr protocol (`herdr status`: `restart_needed`,
`private_protocol_compatible`, `server_binary_stale`), Herdr `--kind`, CLI
binary, **model inventory**, **reasoning effort**. If `ok` is false, print
`fixes` and stop. Protocol mismatch fix is `herdr server stop` then start
`herdr` again. Do not invent another model. Do not reuse a random idle agent.

Slow CLI inventories (`devin models list`) are cached under
`%LOCALAPPDATA%/workflow-herdr/probe-cache.json` (override
`WORKFLOW_HERDR_PROBE_CACHE`, TTL `WORKFLOW_HERDR_PROBE_TTL`, bypass
`--fresh` / `WORKFLOW_HERDR_PROBE_FRESH=1`). Codex models come from
`~/.codex/models_cache.json` when present, then `codex doctor`, then YAML
`known_models`.

**2. Detect with your judgment, not folder names.** `bootstrap` writes a
heuristic `.herdr/detection.yaml` draft (`systems.*.sot` from path clues,
`draft: true`). It does **not** size. Read the excerpts. Confirm or correct
source of truth. Fill `sizing_graph` + `sizing_reason`. Low confidence → ask
the human. Then refresh `.herdr/project.md`.

**3. Size from detection**, not vibes. `sizing_graph` + `sizing_reason` are
required. small / medium / large (or a custom overlay graph). Count runnable
workstreams. Blocked external work first.

**4. Init + one-shot layout** (medium/large):

```text
python scripts/init_work.py --project <abs> --change <change> --volume <graph>
python scripts/workflow_guard.py doctor --project <abs> --change <change> --volume <graph>
python scripts/layout_graph.py --project <abs> --change <change> --volume <graph>
```

Do not hand-split panes. Do not `pane run` a CLI. `layout_graph` splits, records,
`agent start --kind`, labels, and rolls back unstarted panes. The seat brief
(`nodes.*.brief`) is the CLI's initial prompt, passed after `--` at start.
Do not `agent prompt` the brief. Codex often sits on the workspace trust
dialog while Herdr reports `idle`; `agent prompt` then sends Enter and Codex
quits. `start_seat` dismisses that dialog with `agent send-keys enter`
(Yes, continue) before it returns. Every later packet goes through
`prompt_seat.py` (one prompt, no loop): it refuses a shell pane, dismisses
trust, then prompts. Overlay a project brief via `.herdr/workflow.yaml`
`nodes.<seat>.brief`.

Small: layout worker only, no run files.

Large: `identity.streams` or `tasks.workstreams` (≥2). One Orchestrator in the
current workspace. Each stream gets its own worktree plus a Dispatcher+Worker
pair (`number` = stream index, cwd = that worktree). `layout_graph` used to
start a single trio in the last worktree; that was a bug.

**5. Handoff.**

```text
python scripts/prompt_seat.py --project <abs> --change <change> --seat orchestrator --from brain --text "<intent>"
python scripts/orchestrate.py --project <abs> --change <change> --from brain --on goal_created
```

`--from brain` never waits. Dispatcher/Orchestrator waits use
`watch.worker_timeout_ms` / `watch.dispatcher_timeout_ms` (20 min). A wait
timeout is not death: `prompt_seat` returns `timeout: true` and `agent_alive`
if the pane still hosts the agent. Stay with the human.

Never export empty `HERDR_SESSION`. Never mix `--machine` and `--session`.
Idle/done is not acceptance. Receipts are.
