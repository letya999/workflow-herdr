#!/usr/bin/env python3
"""Create one change folder from YAML layout + assets templates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import expand_layout, resolve, skill_dir
from yaml_lite import dump_yaml, load_yaml


CHANGE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


def exclude_local_runtime(project: Path) -> None:
    git_dir = project / ".git"
    if not git_dir.is_dir():
        return
    entry = "/.herdr/"
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if entry not in {line.strip() for line in existing.splitlines()}:
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        exclude.write_text(existing + prefix + entry + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--volume", required=True, choices=("medium", "large"))
    args = parser.parse_args()
    if not CHANGE_NAME.match(args.change):
        print("error: change name must match [a-z][a-z0-9-]{0,47}", file=sys.stderr)
        return 2
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2
    config = resolve(project)
    rel = expand_layout(config, change=args.change)
    exclude_local_runtime(project)
    needed = ("change_dir", "receipts", "session", "state")
    missing = [key for key in needed if key not in rel]
    if missing:
        print(f"error: layout missing keys: {missing}", file=sys.stderr)
        return 2
    assets = skill_dir() / "assets"
    for key in ("change_dir", "receipts"):
        (project / rel[key]).mkdir(parents=True, exist_ok=True)
        print(f"dir {project / rel[key]}")

    copies = {
        "session": "run.template.json",
        "state": "state.template.yaml",
    }
    for key, asset in copies.items():
        dest = project / rel[key]
        if dest.exists():
            print(f"keep {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = (assets / asset).read_text(encoding="utf-8")
        if key == "session":
            data = json.loads(text)
            data.update(
                {"change": args.change, "volume": args.volume, "project": str(project)}
            )
            text = json.dumps(data, indent=2) + "\n"
        else:
            data = load_yaml(text) or {}
            data["workflow"] = args.volume
            text = dump_yaml(data)
        dest.write_text(text, encoding="utf-8")
        print(f"create {dest}")
    print(f"change_dir={project / rel['change_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
