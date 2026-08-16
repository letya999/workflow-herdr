---
name: workflow-herdr
description: >
  Start a Herdr work run for a change. Use when starting work, doing a
  task in Herdr, splitting work across panes, or chatting from a Herdr
  terminal - even if they just say do this. Do NOT use for a solo one-pane
  edit, headless delegates, or product job queues.
---

# Workflow Herdr

Where a change, its plan, and its tasks live is in the YAML, not here.
Copy the example overlay to change CLIs or models without editing this file.

- Config: [workflow.yaml](workflow.yaml)
- Overlay example: [assets/workflow.example.yaml](assets/workflow.example.yaml)
- How to run: [references/run.md](references/run.md)

## Do

Brain owns the conversation with the human: business requirements, intent,
feedback, and authority. Repo docs are context, not the request.

If this process is not a Herdr pane, stop.

Brain chooses exactly one size before creating topology:

- small: Brain -> Worker;
- medium: Brain -> Orchestrator -> Dispatcher -> Worker;
- large: Brain -> Orchestrator -> worktree N -> Dispatcher N -> Worker N.

Small starts work immediately. Medium and large keep intent, specification,
plan, and implementation state distinct. Use the project's existing document
homes. If they do not exist, keep those sections explicit in agent handoffs;
do not create a documentation tree just for this skill.

Resolve blocked or missing work before sizing. Count runnable workstreams, not
issue numbers. Before creating any pane, tab, workspace, or worktree, run the
preflight command from the run reference. If it fails, stop without mutating
topology. Use only panes created by this run; assign role names only to agents
started in those panes.

How to start seats, watch a worker, and move task state is in the run
reference. Load only the section for the chosen volume. Do not open the
agent-runtime note unless the human asked.
