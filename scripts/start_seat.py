#!/usr/bin/env python3
"""Focus a live Herdr agent or start it. Rollback if start fails."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import HerdrError, herdr, result_items, screen_text, value_for
from load_config import (
    agent_name,
    expand_layout,
    native_args,
    node_of,
    pane_label,
    render_brief,
    resolve,
    start_brief_prompt,
)
from run_store import load_identity
from record_pane import record_pane

SHELLS = ("zsh", "bash", "fish", "sh", "dash", "nu", "pwsh", "powershell", "cmd")
TRUST_MARKERS = (
    "do you trust the contents of this directory",
    "working with untrusted contents",
)
TRUST_CHOICE_MARKERS = ("yes, continue", "no, quit")
COMPOSER_MARKERS = ("ask codex to do anything",)
TRUST_KINDS = ("codex",)
TRUST_POLL_S = 0.4
DEFAULT_TRUST_TIMEOUT_MS = 20000


def is_shell(name: str) -> bool:
    lowered = (name or "").lower().replace("\\", "/")
    base = lowered.rsplit("/", 1)[-1]
    stem = base[:-4] if base.endswith(".exe") else base
    return stem in SHELLS


def _session_machine(identity: dict) -> tuple[str | None, str | None]:
    return identity.get("herdr_session"), identity.get("machine")


def looks_like_trust(text: str) -> bool:
    lowered = (text or "").lower()
    if any(marker in lowered for marker in TRUST_MARKERS):
        return True
    return all(marker in lowered for marker in TRUST_CHOICE_MARKERS)


def looks_like_composer(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in COMPOSER_MARKERS)


def dismiss_codex_trust(
    *,
    kind: str,
    name: str,
    session: str | None,
    machine: str | None,
    runner=None,
    sleep=time.sleep,
    timeout_ms: int = DEFAULT_TRUST_TIMEOUT_MS,
) -> dict:
    """Codex reports idle on the workspace trust dialog. agent prompt then sends
    Enter, which can pick No/quit and drop the pane back to a shell."""
    if str(kind or "") not in TRUST_KINDS:
        return {
            "trust_cleared": True,
            "trust_sent_enter": False,
            "trust_error": None,
        }
    timeout_ms = int(timeout_ms or 0)
    if timeout_ms <= 0:
        return {
            "trust_cleared": True,
            "trust_sent_enter": False,
            "trust_error": None,
        }
    attempts = max(1, int(timeout_ms / (TRUST_POLL_S * 1000)) + 1)
    sent = 0
    last = ""
    last_error = None
    for _ in range(attempts):
        try:
            payload = herdr(
                ["agent", "read", name, "--source", "visible", "--lines", "80"],
                session=session,
                machine=machine,
                runner=runner,
            )
            last = screen_text(payload)
            last_error = None
        except HerdrError as exc:
            last_error = exc
            if exc.code == "agent_not_found":
                return {
                    "trust_cleared": False,
                    "trust_sent_enter": sent > 0,
                    "trust_error": "agent_not_found",
                }
            sleep(TRUST_POLL_S)
            continue
        if looks_like_trust(last):
            if sent >= 3:
                sleep(TRUST_POLL_S)
                continue
            try:
                herdr(
                    ["agent", "send-keys", name, "enter"],
                    session=session,
                    machine=machine,
                    runner=runner,
                )
                sent += 1
            except HerdrError as exc:
                last_error = exc
            sleep(TRUST_POLL_S)
            continue
        if looks_like_composer(last) or sent:
            return {
                "trust_cleared": True,
                "trust_sent_enter": sent > 0,
                "trust_error": None,
            }
        sleep(TRUST_POLL_S)
    still_trust = looks_like_trust(last)
    error = None
    if still_trust:
        error = "trust_dialog_still_visible"
    elif last_error is not None:
        error = last_error.code or str(last_error)
    return {
        "trust_cleared": not still_trust,
        "trust_sent_enter": sent > 0,
        "trust_error": error,
    }


def find_live_agent(runner, session, machine, name: str, workspace_id: str | None):
    payload = herdr(["agent", "list"], session=session, machine=machine, runner=runner)
    named = []
    for agent in result_items(payload, "agents"):
        if value_for(agent, "name") != name:
            continue
        named.append(agent)
        agent_ws = value_for(agent, "workspace_id", "workspaceId")
        if workspace_id and agent_ws and agent_ws != workspace_id:
            continue
        return agent
    return named[0] if named else None


def start_seat(
    *,
    project: Path,
    change: str,
    seat: str,
    number: int = 1,
    pane_id: str = "",
    runner=None,
    sleep=time.sleep,
    config: dict | None = None,
) -> dict:
    config = config or resolve(project)
    identity = load_identity(project, change, config)
    session, machine = _session_machine(identity)
    name = agent_name(config, seat, number, change)
    node = node_of(config, seat)
    harness = node.get("harness") or node.get("cli")
    kind = ((config.get("harnesses") or {}).get(harness) or {}).get("kind")
    if not name:
        raise HerdrError(f"{seat} has no Herdr agent name", "no_agent_name")
    if not kind:
        raise HerdrError(f"{seat} harness {harness} has no Herdr kind", "no_kind")

    watch = config.get("watch") or {}
    trust_timeout = int(watch.get("trust_timeout_ms") or DEFAULT_TRUST_TIMEOUT_MS)
    workspace_id = identity.get("workspace_id")
    existing = find_live_agent(runner, session, machine, name, workspace_id)
    if existing:
        herdr(["agent", "focus", name], session=session, machine=machine, runner=runner)
        trust = dismiss_codex_trust(
            kind=str(kind),
            name=name,
            session=session,
            machine=machine,
            runner=runner,
            sleep=sleep,
            timeout_ms=trust_timeout,
        )
        return {
            "action": "focused",
            "agent": name,
            "seat": seat,
            "pane_id": value_for(existing, "pane_id", "paneId"),
            "kind": kind,
            **trust,
        }

    if not pane_id:
        raise HerdrError("pane id required to start a new agent", "missing_pane")
    try:
        brief_body = render_brief(
            config, seat, project=project, change=change, number=number
        )
    except FileNotFoundError as exc:
        raise HerdrError(str(exc), "missing_brief") from exc
    brief_file = None
    if brief_body:
        brief_dir = project / expand_layout(config, change=change)["change_dir"] / "briefs"
        brief_dir.mkdir(parents=True, exist_ok=True)
        brief_file = brief_dir / f"{seat}.md"
        brief_file.write_text(brief_body, encoding="utf-8")
    brief_text = (
        start_brief_prompt(
            config,
            seat,
            project=project,
            change=change,
            number=number,
            brief_file=brief_file,
        )
        if brief_body
        else ""
    )

    busy_retries = int(watch.get("busy_retries") or 8)
    start_timeout = int(watch.get("start_timeout_ms") or 120000)
    created_pane = pane_id
    agent_started = False
    briefed = False
    brief_error = None
    trust = {
        "trust_cleared": True,
        "trust_sent_enter": False,
        "trust_error": None,
    }
    try:
        started = False
        last_error = ""
        for _ in range(busy_retries):
            try:
                args = [
                    "agent",
                    "start",
                    name,
                    "--kind",
                    str(kind),
                    "--pane",
                    pane_id,
                    "--timeout",
                    str(start_timeout),
                ]
                extra = native_args(config, seat, number, change)
                if extra or brief_text:
                    args.append("--")
                    args.extend(extra)
                    if brief_text:
                        args.append(brief_text)
                herdr(args, session=session, machine=machine, runner=runner)
                started = True
                briefed = bool(brief_text)
                break
            except HerdrError as exc:
                last_error = str(exc)
                if exc.code == "agent_pane_busy":
                    sleep(1)
                    continue
                raise
        if not started:
            raise HerdrError(
                last_error or f"shell in {pane_id} never became available",
                "agent_pane_busy",
            )
        agent_started = True
        session_file = project / expand_layout(config, change=change)["session"]
        record_pane(
            session_file,
            config=config,
            pane_id=pane_id,
            seat=seat,
            number=number,
            status="running",
            change=change,
            tab_id=identity.get("tab_id") or "",
        )
        try:
            trust = dismiss_codex_trust(
                kind=str(kind),
                name=name,
                session=session,
                machine=machine,
                runner=runner,
                sleep=sleep,
                timeout_ms=trust_timeout,
            )
        except HerdrError as exc:
            trust = {
                "trust_cleared": False,
                "trust_sent_enter": False,
                "trust_error": exc.code or str(exc),
            }
    except Exception:
        if not agent_started and created_pane:
            try:
                herdr(
                    ["pane", "close", created_pane],
                    session=session,
                    machine=machine,
                    runner=runner,
                )
            except HerdrError:
                pass
        raise

    return {
        "action": "started",
        "agent": name,
        "seat": seat,
        "pane_id": pane_id,
        "kind": kind,
        "pane_label": pane_label(config, seat, number, change),
        "briefed": briefed,
        "brief_error": brief_error,
        **trust,
    }


def ensure_seat_ready(
    *,
    project: Path,
    change: str,
    seat: str,
    number: int = 1,
    runner=None,
    sleep=time.sleep,
    config: dict | None = None,
) -> dict:
    config = config or resolve(project)
    identity = load_identity(project, change, config)
    session, machine = _session_machine(identity)
    name = agent_name(config, seat, number, change)
    node = node_of(config, seat)
    harness = node.get("harness") or node.get("cli")
    kind = ((config.get("harnesses") or {}).get(harness) or {}).get("kind")
    if not name:
        raise HerdrError(f"{seat} has no Herdr agent name", "no_agent_name")
    workspace_id = identity.get("workspace_id")
    existing = find_live_agent(runner, session, machine, name, workspace_id)
    if not existing:
        raise HerdrError(f"live agent {name} not found", "agent_not_found")
    watch = config.get("watch") or {}
    trust = dismiss_codex_trust(
        kind=str(kind),
        name=name,
        session=session,
        machine=machine,
        runner=runner,
        sleep=sleep,
        timeout_ms=int(watch.get("trust_timeout_ms") or DEFAULT_TRUST_TIMEOUT_MS),
    )
    return {
        "action": "ready",
        "agent": name,
        "seat": seat,
        "pane_id": value_for(existing, "pane_id", "paneId"),
        "kind": kind,
        **trust,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--pane", default="")
    parser.add_argument(
        "--ensure-ready",
        action="store_true",
        help="Dismiss Codex trust on a live seat; do not start or prompt",
    )
    args = parser.parse_args()
    project = Path(args.project).resolve()
    try:
        if args.ensure_ready:
            result = ensure_seat_ready(
                project=project,
                change=args.change,
                seat=args.seat,
                number=args.n,
            )
        else:
            result = start_seat(
                project=project,
                change=args.change,
                seat=args.seat,
                number=args.n,
                pane_id=args.pane,
            )
    except HerdrError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
