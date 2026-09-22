#!/usr/bin/env python3
"""One prompt after the Codex trust gate. Does not loop. Timeout is not death."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import HerdrError, herdr, screen_text, value_for
from load_config import agent_name, may_wait, node_of, resolve, wait_timeout_ms
from run_store import load_identity
from start_seat import (
    DEFAULT_TRUST_TIMEOUT_MS,
    dismiss_codex_trust,
    find_live_agent,
    is_shell,
)


def _session_machine(identity: dict) -> tuple[str | None, str | None]:
    return identity.get("herdr_session"), identity.get("machine")


def _agent_blob(payload: dict) -> dict:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    agent = result.get("agent") if isinstance(result.get("agent"), dict) else result
    return agent if isinstance(agent, dict) else {}


def snapshot_agent(name: str, *, session, machine, runner) -> dict:
    try:
        payload = herdr(["agent", "get", name], session=session, machine=machine, runner=runner)
    except HerdrError as exc:
        if exc.code == "agent_not_found":
            return {
                "alive": False,
                "status": "missing",
                "title": "",
                "kind": "",
                "pane_id": "",
            }
        raise
    agent = _agent_blob(payload)
    title = str(value_for(agent, "terminal_title_stripped", "terminal_title") or "")
    status = str(value_for(agent, "agent_status", "status") or "")
    kind = str(value_for(agent, "agent") or "")
    pane_id = str(value_for(agent, "pane_id") or "")
    alive = bool(kind) and not is_shell(title)
    return {
        "alive": alive,
        "status": status,
        "title": title,
        "kind": kind,
        "pane_id": pane_id,
    }


def prompt_seat(
    *,
    project: Path,
    change: str,
    seat: str,
    text: str,
    number: int = 1,
    source: str = "brain",
    wait: bool | None = None,
    timeout_ms: int | None = None,
    runner=None,
    sleep=time.sleep,
    config: dict | None = None,
) -> dict:
    config = config or resolve(project)
    identity = load_identity(project, change, config)
    session, machine = _session_machine(identity)
    name = agent_name(config, seat, number, change)
    if not name:
        raise HerdrError(f"{seat} has no Herdr agent name", "no_agent_name")
    if not (text or "").strip():
        raise HerdrError("prompt text is empty", "empty_prompt")
    node = node_of(config, seat)
    harness = node.get("harness") or node.get("cli")
    kind = ((config.get("harnesses") or {}).get(harness) or {}).get("kind")
    live = find_live_agent(runner, session, machine, name, identity.get("workspace_id"))
    if not live:
        raise HerdrError(f"live agent {name} not found", "agent_not_found")
    snap = snapshot_agent(name, session=session, machine=machine, runner=runner)
    if not snap["alive"]:
        raise HerdrError(
            f"{name} is not an interactive agent ({snap['title'] or snap['status']})",
            "agent_exited",
        )
    watch = config.get("watch") or {}
    trust = dismiss_codex_trust(
        kind=str(kind or snap.get("kind") or ""),
        name=name,
        session=session,
        machine=machine,
        runner=runner,
        sleep=sleep,
        timeout_ms=int(watch.get("trust_timeout_ms") or DEFAULT_TRUST_TIMEOUT_MS),
    )
    if not trust.get("trust_cleared"):
        raise HerdrError(
            f"{name} still on the workspace trust dialog",
            trust.get("trust_error") or "trust_dialog_still_visible",
        )
    if wait is None:
        wait = may_wait(config, source)
    timeout = int(timeout_ms or wait_timeout_ms(config, seat))
    args = ["agent", "prompt", name, text]
    if wait:
        args.extend(["--wait", "--timeout", str(timeout)])
    prompted = False
    timed_out = False
    try:
        herdr(args, session=session, machine=machine, runner=runner)
        prompted = True
    except HerdrError as exc:
        if wait and exc.code == "timeout":
            prompted = True
            timed_out = True
        else:
            raise
    after = snapshot_agent(name, session=session, machine=machine, runner=runner)
    screen = ""
    try:
        payload = herdr(
            ["agent", "read", name, "--source", "visible", "--lines", "40"],
            session=session,
            machine=machine,
            runner=runner,
        )
        screen = screen_text(payload)
    except HerdrError:
        screen = ""
    if not after["alive"]:
        raise HerdrError(f"{name} exited after prompt", "agent_exited")
    return {
        "ok": True,
        "prompted": prompted,
        "timeout": timed_out,
        "settled": wait and prompted and not timed_out,
        "waited": bool(wait),
        "timeout_ms": timeout,
        "agent": name,
        "seat": seat,
        "pane_id": after.get("pane_id") or value_for(live, "pane_id", "paneId"),
        "status": after.get("status"),
        "agent_alive": True,
        **trust,
        "screen": screen[-2000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--text", required=True)
    parser.add_argument("--from", dest="source", default="brain")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--timeout", type=int, default=0)
    args = parser.parse_args()
    if args.wait and args.no_wait:
        print("error: use --wait or --no-wait, not both", file=sys.stderr)
        return 2
    wait: bool | None
    if args.wait:
        wait = True
    elif args.no_wait:
        wait = False
    else:
        wait = None
    project = Path(args.project).resolve()
    try:
        result = prompt_seat(
            project=project,
            change=args.change,
            seat=args.seat,
            text=args.text,
            number=args.n,
            source=args.source,
            wait=wait,
            timeout_ms=args.timeout or None,
        )
    except HerdrError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
