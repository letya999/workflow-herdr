#!/usr/bin/env python3
"""Collect workflow artifacts and the Brain classification schema.

Python lists candidates and excerpts. Brain (this chat) must read them and
write .herdr/detection.yaml. Folder names are clues, not proof.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover import discover
from load_config import expand_layout, resolve
from yaml_lite import dump_yaml, load_yaml

STATE_WORDS = re.compile(
    r"\b(accepted|proposed|superseded|deprecated|draft|active|done|closed|"
    r"in[- ]progress|pending|blocked|ready)\b",
    re.I,
)
FRONT_STATE = re.compile(
    r"^(status|state|lifecycle|stage)\s*:\s*(\S+)", re.I | re.M
)
MAX_EXCERPT = 900
MAX_FILES = 8


def _rel(project: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _excerpt(path: Path, project: Path | None = None) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")[:8000]
    heading = ""
    for line in text.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
            break
    front = FRONT_STATE.search(text[:1200])
    found = STATE_WORDS.findall(text[:2000])
    shown = _rel(project, path) if project is not None else str(path).replace("\\", "/")
    return {
        "path": shown,
        "heading": heading,
        "heuristic_state": (front.group(2) if front else (found[0].lower() if found else None)),
        "excerpt": text[:MAX_EXCERPT],
    }


def collect_group(project: Path, files: list[str]) -> list[dict]:
    out = []
    for relative in files[:MAX_FILES]:
        path = project / relative
        if path.is_file():
            out.append(_excerpt(path, project))
    return out


def collect(project: Path, config: dict | None = None) -> dict:
    config = config or resolve(project)
    raw = discover(project, config)
    groups = {}
    for name, items in (raw.get("groups") or {}).items():
        files: list[str] = []
        existing = []
        for item in items:
            if item.get("exists"):
                existing.append(item.get("path"))
            files.extend(item.get("files") or [])
        groups[name] = {
            "hits": existing,
            "files": files[:MAX_FILES],
            "excerpts": collect_group(project, files),
        }
    layout = expand_layout(config)
    return {
        "groups": groups,
        "detection": layout.get("detection") or ".herdr/detection.yaml",
        "profile": layout.get("profile") or ".herdr/project.md",
    }


def draft_from_groups(groups: dict) -> dict:
    """Heuristic SoT from path clues. Does not size. Brain must confirm."""
    systems = {}
    for key in ("requirements", "adr", "plans", "state"):
        group = groups.get(key) or {}
        hits = [item for item in (group.get("hits") or []) if item]
        excerpts = group.get("excerpts") or []
        if hits:
            state = excerpts[0].get("heuristic_state") if excerpts else None
            systems[key] = {
                "sot": hits[0],
                "confidence": "low",
                "state": state,
            }
        else:
            systems[key] = {"sot": "Not used", "confidence": "high", "state": None}
    open_design = False
    for item in (groups.get("adr") or {}).get("excerpts") or []:
        state = str(item.get("heuristic_state") or "").lower()
        if state in ("draft", "proposed", "pending"):
            open_design = True
            break
    return {
        "systems": systems,
        "open_design_decisions": open_design,
        "independent_workstreams": 1,
        "sizing_graph": "",
        "sizing_reason": "",
        "draft": True,
    }


def write_draft(project: Path, config: dict | None = None) -> dict:
    """Fill systems from clues if detection is missing or still a draft."""
    config = config or resolve(project)
    collected = collect(project, config)
    rel = collected.get("detection") or ".herdr/detection.yaml"
    path = project / rel
    existing = (
        load_yaml(path.read_text(encoding="utf-8")) if path.is_file() else {}
    ) or {}
    if not isinstance(existing, dict):
        existing = {}
    confirmed = bool(
        existing.get("sizing_graph")
        and existing.get("sizing_reason")
        and not existing.get("draft")
    )
    if confirmed:
        return {"path": str(path).replace("\\", "/"), "action": "keep", "draft": existing}
    draft = draft_from_groups(collected.get("groups") or {})
    if existing.get("sizing_graph"):
        draft["sizing_graph"] = existing.get("sizing_graph")
        draft["sizing_reason"] = existing.get("sizing_reason") or ""
        draft["draft"] = not bool(existing.get("sizing_reason"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(draft), encoding="utf-8")
    return {"path": str(path).replace("\\", "/"), "action": "wrote", "draft": draft}


def detect(project: Path, config: dict | None = None) -> dict:
    config = config or resolve(project)
    collected = collect(project, config)
    groups = collected.get("groups") or {}
    detection_rel = collected.get("detection") or ".herdr/detection.yaml"
    profile_rel = collected.get("profile") or ".herdr/project.md"
    detection_path = project / detection_rel
    classified = load_yaml(detection_path.read_text(encoding="utf-8")) if detection_path.is_file() else {}
    brain_task = {
        "instruction": (
            "You are Brain. Read every excerpt. Do not trust a folder name. "
            "Decide the source of truth for requirements, ADR, plans, and project "
            "state. If a system is absent or dead, set sot: Not used. "
            "Then size the CURRENT human request: small (one turn, no design), "
            "medium (one story), large (two or more non-overlapping workstreams). "
            "Write .herdr/detection.yaml using the schema. Low confidence → ask the human."
        ),
        "schema": {
            "systems": {
                "requirements": {"sot": "path or Not used", "confidence": "high|low", "state": "string|null"},
                "adr": {"sot": "path or Not used", "confidence": "high|low", "state": "string|null"},
                "plans": {"sot": "path or Not used", "confidence": "high|low", "state": "string|null"},
                "state": {"sot": "path or Not used", "confidence": "high|low", "state": "string|null"},
            },
            "open_design_decisions": "bool",
            "independent_workstreams": "int",
            "sizing_graph": "small|medium|large|<custom graph>",
            "sizing_reason": "one sentence",
        },
    }
    missing = _schema_gaps(classified) if classified else ["detection.yaml missing"]
    return {
        "ok": not missing,
        "profile": profile_rel,
        "profile_exists": (project / profile_rel).is_file(),
        "detection": detection_rel,
        "classified": classified,
        "gaps": missing,
        "groups": groups,
        "brain_task": brain_task,
        "next": (
            "write detection.yaml then choose sizing_graph"
            if missing
            else f"size={classified.get('sizing_graph')}"
        ),
    }


def _schema_gaps(data: dict) -> list[str]:
    gaps = []
    if not isinstance(data, dict) or not data:
        return ["detection.yaml empty"]
    systems = data.get("systems") or {}
    for key in ("requirements", "adr", "plans", "state"):
        item = systems.get(key) or {}
        if item.get("sot") in (None, ""):
            gaps.append(f"systems.{key}.sot missing")
        if item.get("confidence") not in ("high", "low"):
            gaps.append(f"systems.{key}.confidence must be high|low")
    if "open_design_decisions" not in data:
        gaps.append("open_design_decisions missing")
    if not isinstance(data.get("independent_workstreams"), int):
        gaps.append("independent_workstreams must be an int")
    if not data.get("sizing_graph"):
        gaps.append("sizing_graph missing")
    if not data.get("sizing_reason"):
        gaps.append("sizing_reason missing")
    return gaps


def write_stub(project: Path, config: dict | None = None) -> Path:
    config = config or resolve(project)
    rel = expand_layout(config).get("detection") or ".herdr/detection.yaml"
    path = project / rel
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dump_yaml(
            {
                "systems": {
                    "requirements": {"sot": "", "confidence": "low", "state": None},
                    "adr": {"sot": "", "confidence": "low", "state": None},
                    "plans": {"sot": "", "confidence": "low", "state": None},
                    "state": {"sot": "", "confidence": "low", "state": None},
                },
                "open_design_decisions": False,
                "independent_workstreams": 1,
                "sizing_graph": "",
                "sizing_reason": "",
            }
        ),
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--stub", action="store_true")
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    if args.draft:
        drafted = write_draft(project)
        print(f"{drafted.get('action')} {drafted.get('path')}")
    elif args.stub:
        path = write_stub(project)
        print(f"create {path}")
    result = detect(project)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
