# Project Workflow Profile

Keep `.herdr/project.md` as a short English cache of how the project actually
manages work. Use YAML frontmatter only for freshness. Use Markdown for the
workflow because project methods vary and require judgment.

Build the profile from project instructions, templates, integrations, and a
representative active and completed item. Treat names such as `plans`, `specs`,
or `.work` as clues, not proof. Record `Not used` when a system is absent so
absence is unambiguous. Remove empty subsections, but keep the four main system
sections.

Keep `.herdr/` local through `.git/info/exclude`; `init_work.py` adds this entry
idempotently. Change that policy only when the project explicitly adopts a
shared profile. Do not modify the project's `.gitignore` during initialization.

```markdown
---
updated: YYYY-MM-DD
sources:
  - AGENTS.md
  - path/to/workflow-guide
---

# Project Workflow

## Requirements

### System
Methodology, source of truth, and purpose.

### Structure
Hierarchy and relationships between requirement artifacts.

### Lifecycle
States, transitions, approval, completion, and archival.

### Storage
Paths, formats, and naming conventions.

### Templates and examples
- Template: `path` or `Not used`
- Example: `path` or `Not found`

### Tooling
Commands, integrations, trackers, and automation.

### Rules
When requirements are required, who updates them, and what is not duplicated.

## Architecture Decisions

### System
How decisions are recorded and which methodology is used.

### Structure
Hierarchy and relationships to requirements, plans, and other decisions.

### Lifecycle
Proposal, review, acceptance, rejection, superseding, and archival.

### Storage
Paths, formats, and naming conventions.

### Templates and examples
- Template: `path` or `Not used`
- Example: `path` or `Not found`

### Tooling
Commands, integrations, indexes, generators, and automation.

### Rules
When a decision record is required and how existing decisions change.

## Plans and Work Decomposition

### System
Whether plans are standalone, embedded, external, or not persisted, and which
methodology is used.

### Structure
Decomposition hierarchy and relationships to requirements and decisions.

### Lifecycle
Planning, activation, progress, review, completion, cancellation, and archival.

### Storage
Paths, formats, naming conventions, and required contents.

### Templates and examples
- Template: `path` or `Not used`
- Example: `path` or `Not found`

### Tooling
Commands, task trackers, integrations, and automation.

### Rules
When planning is required and which system owns execution status.

## Project State

### System
Durable project-level state and its source of truth, or `Not used`.

### Structure
Tracked information, hierarchy, relationships, and ownership.

### Lifecycle
Update triggers, transitions, retention, and archival.

### Storage
Paths, formats, naming conventions, and Git policy.

### Templates and examples
- Template: `path` or `Not used`
- Example: `path` or `Not found`

### Tooling
Commands, integrations, and automation used to read or update state.

### Rules
What Herdr may update and how project state differs from Herdr run state.

## End-to-End Workflow

Explain where work originates, how the systems connect, which artifacts change
during execution, what marks completion, and what is archived or retained.

## Task Routing

- Small fix: ...
- Normal change: ...
- Requirement change: ...
- Architectural change: ...
- Investigation: ...

## Herdr Rules

- Artifacts Herdr may create or update: ...
- Artifacts Herdr must not create: ...
- Source-of-truth precedence: ...
- Behavior when workflow is unclear: ...
- Runtime-state policy: ...
```

Update the profile when its sources or observed practice contradict it. Change
only the affected text. Do not rescan the project on every run.
