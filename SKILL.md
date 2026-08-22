---
name: workflow-herdr
description: >
  Start a Herdr work run for a change. Use when starting work, doing a
  task in Herdr, splitting work across panes, or chatting from a Herdr
  terminal - even if they just say do this. Do NOT use for a solo one-pane
  edit, headless delegates, or product job queues.
---

# Workflow Herdr

Herdr coordination lives in its own local directory. Project requirements,
decisions, plans, and durable state stay in the systems the project already uses.

- Config: [workflow.yaml](workflow.yaml)
- Project manifest example: [assets/workflow.example.yaml](assets/workflow.example.yaml)
- Project workflow profile: [references/project-workflow.md](references/project-workflow.md)
- How to run: [references/run.md](references/run.md)

## Do

Brain owns the conversation with the human: business requirements, intent,
feedback, and authority. Repo docs are context, not the request.

If this process is not a Herdr pane, stop.

Before sizing, load `.herdr/project.md`. If it is missing, build it from the
project's instructions, templates, integrations, and representative active and
completed work using the project workflow reference. This is a short cached
understanding, not a new methodology. A directory name alone is not evidence
that the project uses that directory as a current source of truth.

Resolve `workflow.yaml` with the optional project manifest at
`.herdr/workflow.yaml`. The manifest overrides global roles, CLIs, volumes,
guards, task states, and layout for this project only. Merge mappings
recursively; replace lists and scalars. Treat the resolved result as the run
configuration.

Brain chooses exactly one size before creating topology:

- small: Brain -> Worker;
- medium: Brain -> Orchestrator -> Dispatcher -> Worker;
- large: Brain -> Orchestrator -> worktree N -> Dispatcher N -> Worker N.

Small starts work immediately. Medium and large follow the profile's routing,
artifact, lifecycle, hierarchy, and tooling rules. Keep Herdr coordination
state separate from durable project state. If the profile says a system is not
used, do not create it. If the workflow remains unclear, keep context in agent
handoffs and ask before creating or changing project artifacts.

Resolve blocked or missing work before sizing. Count runnable workstreams, not
issue numbers. Before creating any pane, tab, workspace, or worktree, run the
preflight command from the run reference. If it fails, stop without mutating
topology. Use only panes created by this run; assign role names only to agents
started in those panes.

How to start seats, watch a worker, and move task state is in the run
reference. Load only the section for the chosen volume. Do not open the
agent-runtime note unless the human asked.
