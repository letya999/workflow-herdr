# Run

Resolve the global YAML with `.herdr/workflow.yaml`, then read `layout`.
Canonical keys: `harnesses`, `nodes`, `graphs`. `roles` / `volumes` / `clis`
are synthesized for old overlays. Expand `{change}` and `{task}` from the
current run.

If this process is not a Herdr-managed pane, stop.
Need `herdr`, Python 3.10, and the CLIs named under `nodes.*.harness`.
Do not print auth files. Never export empty `HERDR_SESSION`.

## Layers

| Layer | Where | Who writes |
| --- | --- | --- |
| Herdr product | `%APPDATA%/herdr`, named `sessions/<name>/`, `~/.herdr/worktrees` | Herdr CLI only |
| Global index | `%LOCALAPPDATA%/workflow-herdr/index.yaml` (override `WORKFLOW_HERDR_INDEX`) | `init_work.py`, `orchestrate.py` |
| Project overlay | `.herdr/workflow.yaml`, `.herdr/project.md` | Brain, once |
| Run identity | `layout.identity` | `init_work.py` |
| Run binding | `layout.session` (`run.json`) | `record_pane.py`, `worktree_seat.py` |
| Graph cursor | `layout.orchestration` | `orchestrate.py` |
| Plan pointers | `layout.artifacts` | Orchestrator |
| Task board | `layout.state` (`tasks.yaml`; reads legacy `state.yaml`) | Orchestrator / Dispatcher via `task_state.py` |

One active medium/large run per `(herdr_session, project)`. Agent names include
`{change}` and stay inside `[a-z][a-z0-9_-]{0,31}`.

## Commands

Start with doctor, then Brain classifies, then layout. Do not skip.

```text
python scripts/bootstrap.py --project <abs>
python scripts/detect.py --project <abs> --draft
python scripts/workflow_guard.py doctor --project <abs> --volume <graph>
python scripts/init_work.py --project <abs> --change <change> --volume <medium|large>
python scripts/layout_graph.py --project <abs> --change <change> --volume <graph>
python scripts/orchestrate.py --project <abs> --change <change> --from <seat> --on <event>
python scripts/task_state.py --project <abs> --change <change> --dump
python scripts/workflow_guard.py validate --project <abs> --change <change>
python scripts/workflow_guard.py status --project <abs> --change <change>
```

Small does not initialize workflow files. Brain still does not `--wait`.

## Doctor (first)

`bootstrap.py` / `doctor` runs **before size and before any split**.

Live checks, for every startable node in the resolved workflow (or `--volume`):

- `HERDR_ENV=1`, `herdr` on PATH
- Herdr protocol via `herdr status` (`restart_needed`, `private_protocol_compatible`,
  `server_binary_stale`). Mismatch: `herdr server stop` then start `herdr` again
- Herdr `--kind` is in `herdr agent start --help` possible values
- CLI is a Windows-safe binary (not an npm POSIX shim)
- **model** is in the CLI inventory (`grok models`, `devin models list`; Codex
  uses `~/.codex/models_cache.json` when present, then `codex doctor`, then
  `known_models`)
- **reasoning effort** is in the CLI/YAML effort list
- optional `WORKFLOW_HERDR_USAGE_JSON` (`remaining=0` is a hard stop)

Inventories are cached in `%LOCALAPPDATA%/workflow-herdr/probe-cache.json`
(15 min). `bootstrap.py --fresh` or `WORKFLOW_HERDR_PROBE_FRESH=1` bypasses it.

If a seat fails, JSON `fixes` says what to install or which YAML field to change.
Stop. No silent fallback.

After `init_work`, `doctor --change` also pins the session, checks workspace cwd,
and forbids a second active run.

## Detect (Brain, not glob)

`detect.py` lists candidate files **and excerpts**. Folder names are clues.
`bootstrap` / `detect.py --draft` fills a heuristic draft for `systems.*.sot`
(`confidence: low` when a path exists, `Not used` when nothing is there).
It never writes `sizing_graph`. Brain reads the excerpts, confirms or
corrects the draft, fills `sizing_graph` + `sizing_reason`. Low confidence
asks the human. `validate` on medium/large requires this file.

## Layout (one command)

`graphs.*.layout.seats` is the pane list. Medium: orchestrator, dispatcher,
worker in the current workspace, tab renamed to `{change}`. Large: one
Orchestrator in the current workspace; each stream gets a worktree plus a
Dispatcher+Worker pair (`init_work --streams a,b` or `tasks.workstreams`).

```text
python scripts/layout_graph.py --project <abs> --change <change> --volume medium
```

That is `pane split` + `record_pane` + `agent start --kind` + `label_seat`.
If start never reaches a live agent, unstarted panes (and new worktrees) roll
back. Do not hand-type splits. Do not `pane run`. Do not `agent prompt --wait`
immediately after start.

`agent start` uses `--timeout` from `watch.start_timeout_ms` (default 180s).
Devin only gets `--model`; extra flags like `--no-alt-screen` prevent Herdr
from detecting it.

## How to test

From the skill repo, not inside a product pane:

```text
python -m unittest discover -s scripts -p "test_*.py"
```

Live doctor (no pane split), from any shell with `HERDR_ENV=1` and
`HERDR_SESSION=default`:

```text
python scripts/bootstrap.py --project <abs> --volume medium
```

Live layout: open a Herdr pane (or a throwaway tab), then init + layout.
Do not run layout against the Brain pane of a real product tab.

```text
python scripts/init_work.py --project <abs> --change <change> --volume medium --session default --workspace <w> --tab <tab>
python scripts/layout_graph.py --project <abs> --change <change> --volume medium --pane <empty-shell-pane>
python scripts/orchestrate.py --project <abs> --change <change> --from brain --on goal_created
herdr agent list
```

Expect three live names `{change}-orch`, `{change}-disp-1`, `{change}-w-1`.
Brain handoff JSON has `may_wait: false`.

## Graph

| | small | medium | large |
| --- | --- | --- | --- |
| Topology | split in current tab | split in current tab; rename tab/panes | worktree workspace per stream, labeled `{repo} / {change}/{stream}` |
| Artifacts | chat only | profile + plan pointer before dispatch | same, plus non-overlapping file sets |
| Seats | brain + worker | + orchestrator + dispatcher + worker | one dispatcher/worker pair per stream |
| Extra git checkout | no | no | yes; remove after merge (`herdr worktree remove`) |

Follow `graphs.<name>.transitions`, not a linear script. Loop edges
(`progress`, `correction`, `next_task`, `plan_revised`) are the BODW cycle.
After each handoff, record the cursor:

```text
python scripts/orchestrate.py --project <abs> --change <change> --from <seat> --on <event>
```

`may_wait` in that JSON is the wait policy. Brain is always false.

Before sizing, read `.herdr/project.md`. If absent, create it from
[project-workflow.md](project-workflow.md) plus `discover.py`. Never infer a
workflow from one directory name. `.herdr/runs` is coordination state, not
project documentation.

## Seats

Titles and Herdr names come from YAML `nodes`. Do not invent short aliases.

- Brain (this chat): intent, size, authority. No product code. Never
  `agent wait` / `agent prompt --wait` on another seat.
- Orchestrator: read the profile, write plan/task list, update artifacts +
  board. Does not write product source. Does not spawn agents. Medium/large.
- Dispatcher N: start before its Worker. Loop the Worker with
  `agent prompt --wait --timeout` until receipt+diff match, or escalate.
- Worker N: only the assigned task. Write the worker receipt. Do not edit
  the board.

Medium stays in the project cwd. Do not create a worktree or workspace.
Rename the current tab to `{change}` and panes to YAML labels. Start
Dispatcher before Worker. After handoff, Brain returns to the human.

Large: `layout_graph` creates one worktree per stream, then a Dispatcher+Worker
pair in that worktree (`--cwd` is the worktree path). Orchestrator stays in the
home workspace. `worktree_seat.py` still uses `--cwd` (the project), `--branch`,
`--label`, `--no-focus`.
After merge into the source branch, `herdr worktree remove --workspace <id>`.
That deletes the checkout, not the branch. If `agent start` fails before the
agent exists, rollback with `worktree_seat.py --rollback-workspace <id>`.

`--no-focus` on every split. Native args come from YAML `harnesses`.
Immediately after each `pane split` succeeds, record the pane before any
other Herdr control command:

```text
python scripts/record_pane.py --project <abs> --change <change> --seat <seat> --pane <id> --n <n> --status created
```

Stop if this write fails. Then start the agent:

```text
python scripts/start_seat.py --project <abs> --change <change> --seat <seat> --pane <id> --n <n>
python scripts/start_seat.py --project <abs> --change <change> --seat <seat> --n <n> --ensure-ready
```

That focuses a live same-name agent in this workspace, or runs
`herdr agent start <name> --kind <kind> --pane <id> -- <native-args>`.
It retries `agent_pane_busy` and `agent_prompt_stalled`. If start never
reaches `agent_started`, it closes the pane. Codex may be `idle` on
`Do you trust the contents of this directory?`; `agent prompt` pastes
Enter onto that dialog and Codex exits to the shell. After start (and
on `--ensure-ready`), `start_seat` reads the screen and, if the trust
dialog is visible, sends `agent send-keys <name> enter` (option 1 Yes)
until the composer (`Ask Codex to do anything`) is up. Do not prompt
until that dialog is gone. After success, label:

```text
python scripts/label_seat.py --project <abs> --change <change> --seat <seat> --pane <id> --n <n>
```

After `pane move`, re-read IDs (`previous_pane_id`) and pass
`--previous-pane` to `record_pane.py`. Do not keep using the old pane id.

## Watch

Do not raw `herdr agent prompt`. Use one shot:

```text
python scripts/prompt_seat.py --project <abs> --change <change> --seat <seat> --n <n> --from <this-seat> --text "<packet>"
```

`--from brain` never adds `--wait`. Other seats wait with
`watch.worker_timeout_ms` / `watch.dispatcher_timeout_ms` (default 20 min),
not `timeout_ms` (2 min). Do not add `--until idle|done|blocked` on a normal
wait. A wait timeout is not death and not done: read `agent_alive` and the
screen, then prompt again or stop.

Dispatcher owns the Worker loop:

1. `orchestrate --from dispatcher --on assigned`
2. `task_state --task <id> --set assigned` (stamps worker/dispatcher from run.json)
3. `prompt_seat --seat worker --from dispatcher --text "<packet>"`
4. On settle: `agent get` + `agent read` + git diff + worker receipt
5. Progress but not done: another bounded `prompt_seat`, no narration
6. Wrong: `task_state --set rejected`, `orchestrate --on correction`, prompt again
7. Done and receipt matches: `task_state --set in_review`, write
   `{change_dir}/receipts/<task>.dispatcher.md`, `task_state --set accepted`,
   `orchestrate --from dispatcher --on accepted`
8. Need a fact: `task_state --set blocked`, `orchestrate --on blocked`,
   prompt Orchestrator **without wait**

Orchestrator owns the Dispatcher loop the same way (`task_ready`,
`next_task`, `plan_revised`, `accepted`, `rejected`, `plan_closed`).
Orchestrator does not wait on Brain.

Brain after `goal_created` / `goal_ready`: `agent prompt` the next seat
**without** `--wait`, `orchestrate --from brain --on ...`, then stay with
the human. When Orchestrator needs a human, it prompts Brain without wait.

Idle/done is not acceptance. Accept only when receipt and diff match the
task. Grok/Devin idle is not done.

## State

Legal names: YAML `task_states`.

`pending → ready → assigned → running → in_review → accepted|rejected → closed`
plus `blocked`. The worker does not write the board.

```text
python scripts/task_state.py --project <abs> --change <change> --task t1 --set in_review
```

`record_pane.py` owns pane and node entries in `run.json`. Before a phase
transition, `workflow_guard.py validate`. Dispatch on medium/large requires
`artifacts.plan` pointing at a real file.

If agent startup fails, `record_pane.py --status failed --error "<short>"`.
A pane created by this run may be closed only after confirming it contains
no agent. Do not use an older idle agent as fallback.

## Packets

Role text is `nodes.*.brief` (default `assets/briefs/*.md`). At start the
full markdown is copied to `{change_dir}/briefs/{seat}.md`, and a **one-line**
prompt (plus that path) is passed as the CLI initial prompt:
`agent start ... -- <native-args> <one-line-brief>`. Herdr cannot encode
newlines in agent argv. Do not send the brief with `herdr agent prompt`.
The crash is the trust dialog, not focus: `agent prompt` submits text plus
Enter, which can choose `2. No, quit`. `start_seat` clears that dialog
with `send-keys enter` first. Project overlay may point `brief` at
`.herdr/briefs/<seat>.md`. Pane titles are not the role.

Later packets are the job, not a second manifesto:

**Small worker:** do the chat request in the current cwd and report checks.
No workflow files.

**Orchestrator:** Brain's intent, `.herdr/project.md`, discovered ADR/spec/plan
paths. Write `artifacts.yaml` and the task board. Large defines non-overlapping
file sets. Do not spawn agents.

**Dispatcher N:** one task, boundaries, constraints, receipt path, worker
agent name. Loop until accept/reject/block.

**Worker N:** only the assigned task and receipt path. Do not edit state.

Packets contain only the role input. Do not copy full chat transcripts,
skill text, or workflow YAML into downstream prompts.

## Agent-runtime

Off unless the human asked for a machine-evaluated Task around one prompt.
Not a second board.
