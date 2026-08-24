# Run

Resolve the global YAML with `.herdr/workflow.yaml`, then read `layout`. The
project manifest overrides global defaults for this project only. It locates Herdr's local profile and
coordination files only. Project artifacts are located by `.herdr/project.md`.
Expand `{change}` and `{task}` from the current run.

If this process is not a Herdr-managed pane, stop.
Need `herdr`, Python 3.10, and the CLIs named under `roles`.
Do not print auth files.

Medium/large initialization and state:

```text
python scripts/load_config.py --project <abs> --change <change> --paths
python scripts/init_work.py --project <abs> --change <change> --volume <medium|large>
python scripts/task_state.py --project <abs> --change <change> --dump
```

Small does not initialize workflow files. Brain sends the chat intent directly
to one Worker in the current cwd and checks its result.

Resolve missing or blocked external work before choosing a volume. Then run,
before any topology mutation:

```text
python scripts/workflow_guard.py preflight --project <abs> --volume <volume>
```

Preflight returns `seats.<seat>.launch`, a complete shell command with the safe
executable and native args. Send that value unchanged with `herdr pane run` in
a pane created by this run. Do not rebuild it, use `Start-Process`, or replace
the executable with a bare CLI name: Windows may select an extensionless npm
shim that is not a Win32 application (herdrdev/herdr#2685). Wait for Herdr to
detect the agent, then assign that new agent its seat name. Never use an older
pane or agent.

## Volume

One direct change with no planning decision: **small**.
One bounded workstream that needs specification or planning: **medium**.
Two or more runnable, non-overlapping workstreams: **large**.

Follow only `volumes.<name>.sequence`.

| | small | medium | large |
| --- | --- | --- | --- |
| Artifacts | chat only | separated intent/spec/plan/state | same, plus workstream boundaries |
| Seats | brain + one worker | + orchestrator + one dispatcher | + one dispatcher/worker pair per stream |
| Extra git checkout | no | no | yes, one per stream |
| After merge | - | - | remove those checkouts (`herdr worktree remove`) |

Before sizing, read `.herdr/project.md`. If absent, create it by following
[project-workflow.md](project-workflow.md). Use its end-to-end workflow and task
routing for medium/large work. Project systems may combine or omit requirements,
decisions, plans, and durable state. Follow what the profile says; never infer a
current workflow from one directory name. `.herdr/runs` is coordination state,
not project documentation.

## Seats

Titles and Herdr names come from YAML `roles`. Do not invent short aliases.

- Brain (this chat): business intent, human feedback, size, and authority. No product code.
- Orchestrator: understand the project workflow, shape work, define task boundaries, and update Herdr coordination state. Medium/large.
- Dispatcher N: start before one Worker, monitor its scope/progress, give feedback, then accept/reject.
- Worker N: implement only its assigned task and write the worker receipt.

Large: one dispatcher + one worker + one worktree per stream.
After merge into the source branch, remove those worktrees. That deletes
the checkout, not the branch.

Medium stays in the project cwd and does not create a worktree or workspace.
Start Dispatcher before Worker. Brain hands execution monitoring to Dispatcher
and returns only for human feedback, authority changes, or the final result.
Keep one run in the current tab; use the change as the tab label and roles as
pane labels so the sidebar does not present every pane as another Brain.

`--no-focus` on every split. Native args (including no-alt-screen) come
from YAML `clis`. After start:

```text
python scripts/label_seat.py --project <abs> --seat worker --pane <id> --n 1
```

## Watch

Dispatcher uses `herdr agent prompt <name> "..." --wait` with a bounded
timeout. A timeout triggers one `agent get` + `agent read` + diff/receipt
inspection. Real progress gets another bounded wait without narration. No
progress gets one corrective prompt; a second stall returns a blocker to Brain.
Idle/done is not acceptance. Accept only when receipt and diff match the task.

## State

The board is the `state` path in `layout`. Legal names: YAML `task_states`.

`pending → ready → assigned → running → in_review → accepted|rejected → closed`
plus `blocked`. The worker does not write the board.

```text
python scripts/task_state.py --project <abs> --change <change> --task t1 --set in_review
```

Record every resource created by this run in `run.json` immediately. Before a
phase transition, validate the board and run record:

```text
python scripts/workflow_guard.py validate --project <abs> --change <change>
```

If `agent start` fails, read the pane and record the error. A pane created by
this run may be closed only after confirming it contains no agent. Do not use
an older idle agent as fallback.

## Packets

**Small worker:** do the chat request in the current cwd and report checks. No workflow files.

**Orchestrator:** receive Brain's intent, follow `.herdr/project.md`, and update
coordination state. Create or update project artifacts only when its routing and
rules call for them. Otherwise carry the needed context in the handoff. Large
defines non-overlapping file sets. Do not spawn agents.

**Dispatcher N:** own one worker from start. Monitor scope/progress, send at
most one corrective prompt per stall, then verify receipt+diff and move state.

**Worker N:** only the assigned task. Write the receipt. Do not edit state.

Packets contain only the role input: intent or specification reference, task,
boundaries, constraints, and receipt path. Do not copy full chat transcripts,
skill text, or workflow YAML into downstream prompts.

## Agent-runtime

Off unless the human asked for a machine-evaluated Task around one prompt.
Not a second board.
