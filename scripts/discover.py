#!/usr/bin/env python3
"""List project instruction, requirement, ADR, plan, and state candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import resolve

DOC_SUFFIXES = {".md", ".markdown", ".yml", ".yaml", ".txt"}
MAX_FILES = 40


def _collect(root: Path, relative: str) -> dict:
    path = root / relative
    entry = {
        "path": relative.replace("\\", "/"),
        "exists": path.exists(),
        "kind": "missing",
        "files": [],
    }
    if path.is_file():
        entry["kind"] = "file"
        entry["files"] = [relative.replace("\\", "/")]
        return entry
    if not path.is_dir():
        return entry
    entry["kind"] = "dir"
    found: list[str] = []
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        if child.suffix.lower() not in DOC_SUFFIXES:
            continue
        found.append(str(child.relative_to(root)).replace("\\", "/"))
        if len(found) >= MAX_FILES:
            break
    entry["files"] = found
    return entry


def discover(project: Path, config: dict | None = None) -> dict:
    config = config or resolve(project)
    discovery = config.get("discovery") or {}
    groups = {}
    for group, paths in discovery.items():
        items = []
        for relative in paths or []:
            items.append(_collect(project, str(relative)))
        groups[group] = items
    profile = (config.get("layout") or {}).get("profile") or ".herdr/project.md"
    return {
        "ok": True,
        "profile": profile,
        "profile_exists": (project / profile).is_file(),
        "groups": groups,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    result = discover(project)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
