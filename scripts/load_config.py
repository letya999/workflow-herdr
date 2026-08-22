#!/usr/bin/env python3
"""Resolve global workflow.yaml plus an optional project manifest. Print JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from yaml_lite import deep_merge, load_yaml


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def read_yaml(path: Path) -> dict:
    return load_yaml(path.read_text(encoding="utf-8")) or {}


def expand_layout(config: dict, change: str = "", task: str = "") -> dict[str, str]:
    raw = dict(config.get("layout") or {})
    values: dict[str, str] = {"change": change, "task": task}
    for _ in range(6):
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
    return data


def format_template(template: str, values: dict) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", "" if value is None else str(value))
    return out


def native_args(config: dict, seat: str, worker_index: int | None = None) -> list[str]:
    role = config["roles"][seat]
    cli_name = role.get("cli")
    cli = (config.get("clis") or {}).get(cli_name) or {}
    values = {
        "model": role.get("model"),
        "effort": role.get("effort"),
        "title": role.get("title"),
        "cli": cli_name,
        "n": worker_index if worker_index is not None else 1,
    }
    args = []
    for part in cli.get("native_args") or []:
        args.append(format_template(str(part), values))
    return args


def agent_name(config: dict, seat: str, worker_index: int | None = None) -> str | None:
    role = config["roles"][seat]
    if role.get("cli") == "human" or role.get("start") is False:
        return None
    if role.get("agent_name_pattern"):
        n = 1 if worker_index is None else worker_index
        return format_template(role["agent_name_pattern"], {"n": n})
    return role.get("agent_name")


def pane_label(config: dict, seat: str, worker_index: int | None = None) -> str:
    role = config["roles"][seat]
    vis = config.get("visibility") or {}
    many = bool(role.get("many"))
    template = vis.get("pane_label_many") if many else vis.get("pane_label")
    if not template:
        template = (
            "{title} {n} | {cli} {model} {effort}"
            if many
            else "{title} | {cli} {model} {effort}"
        )
    n = 1 if worker_index is None else worker_index
    name = agent_name(config, seat, n)
    return format_template(
        template,
        {
            "title": role.get("title"),
            "cli": role.get("cli"),
            "model": role.get("model") or "-",
            "effort": role.get("effort") or "-",
            "agent_name": name or role.get("agent_name") or seat,
            "n": n,
        },
    )


def display_agent(config: dict, seat: str, worker_index: int | None = None) -> str:
    role = config["roles"][seat]
    vis = config.get("visibility") or {}
    many = bool(role.get("many"))
    template = vis.get("display_agent_many") if many else vis.get("display_agent")
    if not template:
        template = "{title} {n}" if many else "{title}"
    n = 1 if worker_index is None else worker_index
    return format_template(template, {"title": role.get("title"), "n": n})


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
        if args.seat not in config.get("roles", {}):
            print(f"error: unknown seat {args.seat}", file=sys.stderr)
            return 2
        role = config["roles"][args.seat]
        cli = (config.get("clis") or {}).get(role.get("cli")) or {}
        payload["seat"] = {
            "id": args.seat,
            "title": role.get("title"),
            "agent_name": agent_name(config, args.seat, args.n),
            "herdr_kind": cli.get("herdr_kind"),
            "cli": role.get("cli"),
            "model": role.get("model"),
            "effort": role.get("effort"),
            "native_args": native_args(config, args.seat, args.n),
            "pane_label": pane_label(config, args.seat, args.n),
            "display_agent": display_agent(config, args.seat, args.n),
            "start": role.get("start", True),
        }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
