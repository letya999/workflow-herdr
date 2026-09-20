#!/usr/bin/env python3
"""Resolve workflow.yaml plus an optional project overlay. Print JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from yaml_lite import deep_merge, load_yaml

AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
KIND_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def read_yaml(path: Path) -> dict:
    return load_yaml(path.read_text(encoding="utf-8")) or {}


def expand_layout(config: dict, change: str = "", task: str = "") -> dict[str, str]:
    raw = dict(config.get("layout") or {})
    values: dict[str, str] = {"change": change, "task": task}
    for _ in range(8):
        for key, template in raw.items():
            if isinstance(template, str):
                values[key] = format_template(template, values)
    return {key: values[key] for key in raw if key in values}


def resolve(project: Path | None) -> dict:
    root = skill_dir()
    data = read_yaml(root / "workflow.yaml")
    if project:
        layout = expand_layout(data, change="_")
        manifest_path = layout.get("manifest") or layout.get("overlay")
        manifest = Path(project) / (manifest_path or ".herdr/workflow.yaml")
        if manifest.is_file():
            data = deep_merge(data, read_yaml(manifest))
    return normalize(data)


def format_template(template: str, values: dict) -> str:
    out = template
    for key, value in values.items():
        token = "" if value is None else str(value)
        out = out.replace("{" + key + "}", token)
    return out


def normalize(data: dict) -> dict:
    """Keep nodes/graphs canonical and synthesize roles/volumes/clis."""
    harnesses = dict(data.get("harnesses") or {})
    clis = dict(data.get("clis") or {})
    if harnesses:
        for name, harness in harnesses.items():
            cli = dict(clis.get(name) or {})
            if "herdr_kind" not in cli:
                cli["herdr_kind"] = harness.get("kind")
            if "native_args" not in cli:
                cli["native_args"] = list(harness.get("args") or [])
            clis[name] = cli
    elif clis:
        for name, cli in clis.items():
            harnesses.setdefault(
                name,
                {
                    "kind": cli.get("herdr_kind"),
                    "args": list(cli.get("native_args") or []),
                    "efforts": [],
                },
            )
    data["harnesses"] = harnesses
    data["clis"] = clis

    nodes = dict(data.get("nodes") or {})
    roles = dict(data.get("roles") or {})
    for key, role in roles.items():
        node = dict(nodes.get(key) or {})
        if "cli" in role and "harness" not in role:
            node["harness"] = role["cli"]
        if "harness" in role:
            node["harness"] = role["harness"]
        if "name" in role:
            node["name"] = role["name"]
        elif "agent_name_pattern" in role:
            node["name"] = role["agent_name_pattern"]
        elif "agent_name" in role:
            node["name"] = role["agent_name"]
        for field, value in role.items():
            if field in ("cli", "agent_name_pattern", "agent_name", "harness", "name"):
                continue
            node[field] = value
        nodes[key] = node
    rebuilt_roles: dict = {}
    for key, node in nodes.items():
        harness = node.get("harness") or node.get("cli") or "human"
        rebuilt_roles[key] = {
            "title": node.get("title") or key,
            "cli": harness,
            "model": node.get("model"),
            "effort": node.get("effort"),
            "start": node.get("start", True),
            "many": bool(node.get("many") or node.get("instances") not in (None, 1, "1")),
            "agent_name": node.get("agent_name"),
            "agent_name_pattern": node.get("name") or node.get("agent_name_pattern"),
            "notes": node.get("notes"),
        }
    data["nodes"] = nodes
    data["roles"] = rebuilt_roles

    graphs = dict(data.get("graphs") or {})
    volumes = dict(data.get("volumes") or {})
    if graphs:
        for name, graph in graphs.items():
            graph = dict(graph)
            volume = dict(volumes.get(name) or {})
            if volume.get("seats"):
                graph["nodes"] = list(volume["seats"])
            volume.setdefault("use_when", graph.get("use_when"))
            volume.setdefault("project_artifacts", graph.get("project_artifacts"))
            volume.setdefault("coordination_state", graph.get("coordination_state"))
            volume.setdefault("worktrees", graph.get("worktrees"))
            volume.setdefault("parallel", graph.get("parallel"))
            volume["seats"] = list(graph.get("nodes") or [])
            if "sequence" not in volume:
                volume["sequence"] = _sequence_from_graph(graph)
            graphs[name] = graph
            volumes[name] = volume
    elif volumes:
        for name, volume in volumes.items():
            graphs.setdefault(
                name,
                {
                    "use_when": volume.get("use_when"),
                    "topology": (
                        "worktree_workspace_per_stream"
                        if volume.get("worktrees")
                        else "split_in_current_tab"
                    ),
                    "project_artifacts": volume.get("project_artifacts"),
                    "coordination_state": volume.get("coordination_state"),
                    "worktrees": volume.get("worktrees"),
                    "parallel": volume.get("parallel"),
                    "nodes": list(volume.get("seats") or []),
                    "entry": "brain",
                    "transitions": _transitions_from_sequence(volume.get("sequence") or []),
                },
            )
    data["graphs"] = graphs
    data["volumes"] = volumes
    return data


def _sequence_from_graph(graph: dict) -> list[dict]:
    seen: list[str] = []
    sequence: list[dict] = []
    for transition in graph.get("transitions") or []:
        owner = transition.get("from")
        event = transition.get("on")
        ident = f"{owner}:{event}"
        if ident in seen:
            continue
        seen.append(ident)
        sequence.append(
            {
                "id": str(event).replace(" ", "_"),
                "owner": owner,
                "gate": event,
            }
        )
    return sequence


def _transitions_from_sequence(sequence: list) -> list[dict]:
    transitions: list[dict] = []
    previous = None
    for step in sequence:
        if not isinstance(step, dict):
            continue
        owner = step.get("owner")
        if previous and owner and previous != owner:
            transitions.append(
                {"from": previous, "to": owner, "on": step.get("id") or "next"}
            )
        previous = owner
    return transitions


def node_of(config: dict, seat: str) -> dict:
    return (config.get("nodes") or {}).get(seat) or (config.get("roles") or {}).get(seat) or {}


def brief_path(config: dict, seat: str, project: Path | None = None) -> Path | None:
    rel = node_of(config, seat).get("brief")
    if not rel:
        return None
    relative = Path(str(rel))
    if relative.is_absolute() and relative.is_file():
        return relative
    if project is not None:
        local = Path(project) / relative
        if local.is_file():
            return local
    bundled = skill_dir() / relative
    if bundled.is_file():
        return bundled
    return None


def render_brief(
    config: dict,
    seat: str,
    *,
    project: Path,
    change: str = "",
    number: int = 1,
) -> str:
    node = node_of(config, seat)
    declared = node.get("brief")
    if not declared:
        return ""
    path = brief_path(config, seat, project)
    if path is None:
        raise FileNotFoundError(f"{seat} brief missing: {declared}")
    owns = node.get("owns") or []
    owned = ", ".join(str(item) for item in owns) if isinstance(owns, list) else str(owns)
    title = node.get("title") or seat
    header = (
        f"You are {title} ({seat}) for change {change or '-'}. "
        f"cwd={project}. owns: {owned or 'none'}.\n\n"
    )
    return header + path.read_text(encoding="utf-8").strip() + "\n"


def flatten_brief(text: str) -> str:
    """One argv-safe line: Herdr rejects newlines/quotes in agent start args."""
    flat = " ".join((text or "").split())
    return flat.replace("'", "").replace('"', "")


def start_brief_prompt(
    config: dict,
    seat: str,
    *,
    project: Path,
    change: str = "",
    number: int = 1,
    brief_file: Path | None = None,
) -> str:
    node = node_of(config, seat)
    title = node.get("title") or seat
    owns = node.get("owns") or []
    owned = ", ".join(str(item) for item in owns) if isinstance(owns, list) else str(owns)
    body = flatten_brief(render_brief(config, seat, project=project, change=change, number=number))
    pointer = ""
    if brief_file is not None:
        pointer = f" Full role: {brief_file.as_posix()}."
    lead = (
        f"You are {title} ({seat}) for change {change or '-'}. "
        f"cwd={Path(project).as_posix()}. owns: {owned or 'none'}.{pointer}"
    )
    if body:
        return flatten_brief(f"{lead} {body}")
    return flatten_brief(lead)


def native_args(
    config: dict, seat: str, worker_index: int | None = None, change: str = ""
) -> list[str]:
    node = node_of(config, seat)
    harness_name = node.get("harness") or node.get("cli")
    harness = (config.get("harnesses") or {}).get(harness_name) or {}
    cli = (config.get("clis") or {}).get(harness_name) or {}
    values = {
        "model": node.get("model"),
        "effort": node.get("effort"),
        "title": node.get("title"),
        "cli": harness_name,
        "n": worker_index if worker_index is not None else 1,
        "change": change,
    }
    parts = harness.get("args") if harness.get("args") is not None else cli.get("native_args")
    return [format_template(str(part), values) for part in parts or []]


def raw_agent_name(
    config: dict, seat: str, worker_index: int | None = None, change: str = ""
) -> str | None:
    node = node_of(config, seat)
    if node.get("harness") == "human" or node.get("cli") == "human" or node.get("start") is False:
        if not node.get("name") and not node.get("agent_name") and not node.get("agent_name_pattern"):
            return None
    n = 1 if worker_index is None else worker_index
    template = node.get("name") or node.get("agent_name_pattern") or node.get("agent_name")
    if not template:
        return None
    prefix = f"{change}-" if change else ""
    text = str(template).replace("{change}-", prefix).replace("{change}", change)
    text = format_template(text, {"n": n, "change": change})
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or None


def agent_name(
    config: dict, seat: str, worker_index: int | None = None, change: str = ""
) -> str | None:
    raw = raw_agent_name(config, seat, worker_index, change)
    if raw is None:
        return None
    return constrain_agent_name(raw, f"{change}:{seat}:{worker_index or 1}")


def constrain_agent_name(raw: str, seed: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-")
    if not slug:
        slug = "n"
    if not slug[0].isalpha():
        slug = "n-" + slug
    if AGENT_NAME_RE.match(slug):
        return slug
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:7]
    base = re.sub(r"[^a-z0-9]+", "", slug)[:12] or "n"
    if not base[0].isalpha():
        base = "n" + base[1:]
    return f"{base}-{digest}"[:32]


def pane_label(
    config: dict, seat: str, worker_index: int | None = None, change: str = ""
) -> str:
    node = node_of(config, seat)
    vis = config.get("visibility") or {}
    many = bool(node.get("many") or node.get("instances") not in (None, 1, "1"))
    template = vis.get("pane_label_many") if many else vis.get("pane_label")
    if not template:
        template = (
            "{title} {n} | {cli} {model} {effort}"
            if many
            else "{title} | {cli} {model} {effort}"
        )
    n = 1 if worker_index is None else worker_index
    harness = node.get("harness") or node.get("cli")
    name = agent_name(config, seat, n, change)
    return format_template(
        template,
        {
            "title": node.get("title") or seat,
            "cli": harness,
            "model": node.get("model") or "-",
            "effort": node.get("effort") or "-",
            "agent_name": name or node.get("agent_name") or seat,
            "n": n,
            "change": change,
        },
    )


def display_agent(
    config: dict, seat: str, worker_index: int | None = None, change: str = ""
) -> str:
    node = node_of(config, seat)
    vis = config.get("visibility") or {}
    many = bool(node.get("many") or node.get("instances") not in (None, 1, "1"))
    template = vis.get("display_agent_many") if many else vis.get("display_agent")
    if not template:
        template = "{title} {n}" if many else "{title}"
    n = 1 if worker_index is None else worker_index
    return format_template(
        template, {"title": node.get("title") or seat, "n": n, "change": change}
    )


def graph_of(config: dict, name: str) -> dict:
    return (config.get("graphs") or {}).get(name) or {}


def event_matches(on_value, event: str) -> bool:
    if isinstance(on_value, list):
        return event in on_value
    return on_value == event


def next_nodes(graph: dict, source: str, event: str) -> list[str]:
    found: list[str] = []
    for transition in graph.get("transitions") or []:
        if transition.get("from") != source:
            continue
        if event_matches(transition.get("on"), event):
            target = transition.get("to")
            if target and target not in found:
                found.append(target)
    return found


def has_edge(graph: dict, source: str, target: str) -> bool:
    for transition in graph.get("transitions") or []:
        if transition.get("from") == source and transition.get("to") == target:
            return True
    return False


def matching_transitions(graph: dict, source: str, event: str) -> list[dict]:
    found: list[dict] = []
    for transition in graph.get("transitions") or []:
        if transition.get("from") != source:
            continue
        if event_matches(transition.get("on"), event):
            found.append(transition)
    return found


def may_wait(config: dict, seat: str) -> bool:
    if seat == "brain":
        return False
    node = node_of(config, seat)
    if node.get("harness") == "human" or node.get("cli") == "human":
        return False
    if node.get("start") is False:
        return False
    return True


def wait_timeout_ms(config: dict, seat: str) -> int:
    watch = config.get("watch") or {}
    default = int(watch.get("timeout_ms") or 120000)
    if seat == "worker":
        return int(watch.get("worker_timeout_ms") or default)
    if seat == "dispatcher":
        return int(
            watch.get("dispatcher_timeout_ms") or watch.get("worker_timeout_ms") or default
        )
    return default


def workspace_label(config: dict, *, repo: str, change: str, stream: str = "") -> str:
    vis = config.get("visibility") or {}
    template = vis.get("workspace_label_stream") if stream else vis.get("workspace_label")
    template = template or ("{repo} / {change}/{stream}" if stream else "{repo} / {change}")
    return format_template(
        template, {"repo": repo, "change": change, "stream": stream}
    )


def tab_label(config: dict, *, change: str, stream: str = "") -> str:
    vis = config.get("visibility") or {}
    template = vis.get("tab_label_stream") if stream else vis.get("tab_label")
    template = template or ("{change}/{stream}" if stream else "{change}")
    return format_template(template, {"change": change, "stream": stream})


def validate_graph(config: dict, name: str) -> list[str]:
    errors: list[str] = []
    graph = graph_of(config, name)
    nodes = config.get("nodes") or {}
    if not graph:
        return [f"unknown graph: {name}"]
    graph_nodes = list(graph.get("nodes") or [])
    for node_id in graph_nodes:
        if node_id not in nodes:
            errors.append(f"{name}: unknown node {node_id}")
    entry = graph.get("entry")
    if entry and entry not in graph_nodes:
        errors.append(f"{name}: entry {entry} is not in graph nodes")
    for transition in graph.get("transitions") or []:
        source = transition.get("from")
        target = transition.get("to")
        event = transition.get("on")
        if source not in nodes:
            errors.append(f"{name}: transition from unknown node {source}")
        if target not in nodes:
            errors.append(f"{name}: transition to unknown node {target}")
        if not event:
            errors.append(f"{name}: transition {source} -> {target} has no event")
    if name != "small" and has_edge(graph, "brain", "worker"):
        errors.append(f"{name} must not contain brain -> worker")
    if name == "small" and "orchestrator" in graph_nodes:
        errors.append("small must not include orchestrator")
    if not may_wait(config, "brain"):
        pass
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--change", default="")
    parser.add_argument("--task", default="")
    parser.add_argument("--paths", action="store_true")
    parser.add_argument("--seat", default="")
    parser.add_argument("--n", type=int, default=1)
    args = parser.parse_args()
    project = Path(args.project) if args.project else None
    try:
        config = resolve(project)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    payload: dict = {"config": config}
    if args.paths:
        if not args.change:
            print("error: --paths needs --change", file=sys.stderr)
            return 2
        rel = expand_layout(config, change=args.change, task=args.task)
        root = Path(args.project).resolve() if args.project else Path.cwd()
        payload["paths"] = {key: str(root / value) for key, value in rel.items()}
        payload["rel"] = rel
    if args.seat:
        nodes = config.get("nodes") or config.get("roles") or {}
        if args.seat not in nodes:
            print(f"error: unknown seat {args.seat}", file=sys.stderr)
            return 2
        node = node_of(config, args.seat)
        harness_name = node.get("harness") or node.get("cli")
        harness = (config.get("harnesses") or {}).get(harness_name) or {}
        payload["seat"] = {
            "id": args.seat,
            "title": node.get("title"),
            "agent_name": agent_name(config, args.seat, args.n, args.change),
            "herdr_kind": harness.get("kind"),
            "cli": harness_name,
            "model": node.get("model"),
            "effort": node.get("effort"),
            "native_args": native_args(config, args.seat, args.n, args.change),
            "pane_label": pane_label(config, args.seat, args.n, args.change),
            "display_agent": display_agent(config, args.seat, args.n, args.change),
            "start": node.get("start", True),
            "owns": node.get("owns") or [],
        }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
