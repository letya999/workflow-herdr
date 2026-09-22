#!/usr/bin/env python3
"""Advance the graph cursor. File helper only; does not call herdr agent prompt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import graph_of, matching_transitions, may_wait, resolve
from run_store import (
    bump,
    load_identity,
    load_orchestration,
    now_stamp,
    save_orchestration,
    upsert_index_run,
)


def advance(
    project: Path,
    change: str,
    source: str,
    event: str,
    *,
    writer: str = "",
    config: dict | None = None,
) -> dict:
    config = config or resolve(project)
    identity = load_identity(project, change, config)
    volume = identity.get("volume") or identity.get("graph")
    graph = graph_of(config, volume) if volume else {}
    if not graph:
        raise ValueError(f"unknown graph: {volume}")
    matches = matching_transitions(graph, source, event)
    if not matches:
        raise ValueError(f"no transition {source} -[{event}]-> in graph {volume}")
    targets = []
    looping = False
    for item in matches:
        target = item.get("to")
        if target and target not in targets:
            targets.append(target)
        if item.get("loop"):
            looping = True
    current = targets[-1]
    data = load_orchestration(project, change, config)
    history = list(data.get("history") or [])
    history.append(
        {
            "from": source,
            "on": event,
            "to": current,
            "loop": looping,
        }
    )
    data["current_node"] = current
    data["last_event"] = event
    data["history"] = history[-50:]
    bump(data, writer or source)
    save_orchestration(project, change, data, config)
    if event in ("plan_closed",) or (current == "brain" and event in ("plan_closed", "need_human")):
        if event == "plan_closed":
            upsert_index_run(
                {
                    "project": str(project.resolve()),
                    "change": change,
                    "herdr_session": identity.get("herdr_session"),
                    "status": "closed",
                    "updated_at": now_stamp(),
                }
            )
    waiters = [seat for seat in targets if may_wait(config, seat)]
    wait = may_wait(config, source)
    return {
        "ok": True,
        "from": source,
        "on": event,
        "to": targets,
        "current_node": current,
        "loop": looping,
        "may_wait": wait,
        "brain_waits": False,
        "wait_on": waiters,
        "prompt": (
            "python scripts/prompt_seat.py --from brain without --wait; keep talking to the human"
            if not wait
            else "python scripts/prompt_seat.py --from this seat; wait timeout is not death"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--from", dest="source", required=True)
    parser.add_argument("--on", required=True)
    parser.add_argument("--by", default="")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    try:
        result = advance(
            project, args.change, args.source, args.on, writer=args.by
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
