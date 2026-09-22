"""Pinned Herdr CLI calls. Never fall back to another session."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Callable

Runner = Callable[[list[str]], dict]


class HerdrError(RuntimeError):
    def __init__(self, message: str, code: str = "", payload: dict | None = None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


def session_argv(session: str | None, machine: str | None = None) -> list[str]:
    args: list[str] = []
    if machine and machine not in ("", "local"):
        args.extend(["--machine", machine])
        return args
    if session and session not in ("", "default"):
        args.extend(["--session", session])
    return args


def assert_session_pin(identity_session: str, env: dict | None = None) -> None:
    env = env or os.environ
    live = (env.get("HERDR_SESSION") or "").strip()
    wanted = (identity_session or "").strip()
    if live == "":
        return
    if wanted in ("", "default"):
        if live not in ("", "default"):
            raise HerdrError(
                f"HERDR_SESSION={live} does not match identity session default",
                "session_mismatch",
            )
        return
    if live != wanted:
        raise HerdrError(
            f"HERDR_SESSION={live} does not match identity session {wanted}",
            "session_mismatch",
        )


def parse_herdr_output(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HerdrError(f"Unexpected non-JSON Herdr output: {text[:200]}", "bad_json") from exc


def is_plain_output_command(args: list[str]) -> bool:
    """agent/pane read print the screen as text, not JSON."""
    for index, part in enumerate(args):
        if part in {"agent", "pane"} and index + 1 < len(args) and args[index + 1] == "read":
            return True
    return False


def screen_text(payload: dict | str | None) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    blobs: list[dict] = [payload]
    result = payload.get("result")
    if isinstance(result, dict):
        blobs.insert(0, result)
    elif isinstance(result, str) and result.strip():
        return result
    for blob in blobs:
        for key in ("text", "output", "content", "snapshot"):
            value = blob.get(key)
            if isinstance(value, str) and value.strip():
                return value
        lines = blob.get("lines")
        if isinstance(lines, list) and lines:
            return "\n".join(str(item) for item in lines)
    return ""


def error_code(payload: dict | str) -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error") or {}
    if isinstance(error, dict):
        return str(error.get("code") or "")
    return ""


def subprocess_runner(env: dict | None = None) -> Runner:
    inherited = dict(env or os.environ)
    if inherited.get("HERDR_SESSION") == "":
        inherited.pop("HERDR_SESSION", None)

    def run(args: list[str]) -> dict:
        executable = inherited.get("HERDR_BIN_PATH") or "herdr"
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            env=inherited,
        )
        output = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.returncode != 0:
            payload = {}
            for blob in (output, err):
                try:
                    payload = json.loads(blob) if blob else {}
                except json.JSONDecodeError:
                    continue
                else:
                    break
            code = error_code(payload) if payload else ""
            raise HerdrError(err or output or f"herdr {' '.join(args)} failed", code, payload)
        if is_plain_output_command(args):
            try:
                parsed = json.loads(output) if output else {}
            except json.JSONDecodeError:
                return {"text": result.stdout or ""}
            if isinstance(parsed, dict):
                return parsed
            return {"text": result.stdout or ""}
        return parse_herdr_output(output)

    return run


def herdr(
    args: list[str],
    *,
    session: str | None = None,
    machine: str | None = None,
    runner: Runner | None = None,
) -> dict:
    prefix = session_argv(session, machine)
    run = runner or subprocess_runner()
    return run([*prefix, *args])


def result_items(payload: dict, key: str) -> list:
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, dict) and key in result:
        value = result[key]
    else:
        value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, list) else []


def value_for(item: dict | None, *names: str) -> Any:
    if not isinstance(item, dict):
        return None
    for name in names:
        if name in item and item[name] not in (None, ""):
            return item[name]
    return None
