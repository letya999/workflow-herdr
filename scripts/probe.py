#!/usr/bin/env python3
"""Live inventory: Herdr kinds, CLI binaries, models, reasoning efforts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

KIND_LINE = re.compile(r"possible values:\s*([a-z0-9][a-z0-9,\s|]+)", re.I)
GROK_MODEL = re.compile(r"^[\s*+\-]+([a-z][a-z0-9._-]*)", re.M)
DEVIN_ID = re.compile(r"^  ([a-z][a-z0-9._-]{1,80})\s{2,}", re.M)
DEVIN_ALIAS = re.compile(r"aliases:\s*(.+)", re.I)
DEVIN_FAMILY = re.compile(r"\(([a-z][a-z0-9._-]*)\)")
EFFORT_VALUES = re.compile(
    r"possible values:\s*([a-z][a-z0-9,\s|/_\-]+)", re.I
)

INVENTORY_CMDS = {
    "grok": {"models": ["models"]},
    "devin": {"models": ["models", "list"]},
    "codex": {"doctor": ["doctor"]},
}
KNOWN_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
}

DEFAULT_TIMEOUT = 90
DEFAULT_CACHE_TTL = 900
PROTOCOL_FIX = (
    "herdr server stop then start herdr again "
    "(pane processes die; layout snapshot-restores)"
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def parse_herdr_kinds(text: str) -> list[str]:
    match = KIND_LINE.search(text or "")
    if not match:
        return []
    blob = match.group(1).replace("|", ",").replace("\n", ",")
    kinds = []
    for part in blob.split(","):
        name = part.strip().lower()
        if name and name not in kinds:
            kinds.append(name)
    return kinds


def parse_grok_models(text: str) -> dict:
    ids: list[str] = []
    for match in GROK_MODEL.finditer(text or ""):
        name = match.group(1)
        if name not in ids:
            ids.append(name)
    return {"ids": ids, "aliases": [], "source": "grok models"}


def parse_devin_models(text: str) -> dict:
    ids: list[str] = []
    aliases: list[str] = []
    for match in DEVIN_ID.finditer(text or ""):
        name = match.group(1)
        if name not in ids:
            ids.append(name)
    for match in DEVIN_ALIAS.finditer(text or ""):
        for part in match.group(1).split(","):
            name = part.strip().lower()
            if name and name not in aliases:
                aliases.append(name)
    for match in DEVIN_FAMILY.finditer(text or ""):
        name = match.group(1)
        if name not in aliases:
            aliases.append(name)
    return {"ids": ids, "aliases": aliases, "source": "devin models list"}


def model_matches(requested: str, inventory: dict, effort: str | None = None) -> bool:
    if not requested:
        return False
    ids = list(inventory.get("ids") or [])
    aliases = list(inventory.get("aliases") or [])
    pool = ids + aliases
    if requested in pool:
        return True
    want = _norm(requested)
    if any(_norm(item) == want for item in pool):
        return True
    if effort:
        combo = f"{requested}-{effort}"
        if combo in pool or _norm(combo) in {_norm(item) for item in pool}:
            return True
        dashed = re.sub(r"([a-z])([0-9])", r"\1-\2", requested.lower())
        combo2 = f"{dashed}-{effort}"
        if combo2 in pool or _norm(combo2) in {_norm(item) for item in pool}:
            return True
    return False


def parse_help_efforts(text: str, flag: str = "reasoning-effort") -> list[str]:
    if not text:
        return []
    window = text
    idx = text.lower().find(flag)
    if idx >= 0:
        window = text[idx : idx + 400]
    match = EFFORT_VALUES.search(window)
    if not match:
        return []
    values = []
    for part in match.group(1).replace("|", ",").split(","):
        name = part.strip().lower()
        if name in KNOWN_EFFORTS and name not in values:
            values.append(name)
    return values


def probe_cache_path() -> Path:
    override = os.environ.get("WORKFLOW_HERDR_PROBE_CACHE")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "workflow-herdr" / "probe-cache.json"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "workflow-herdr" / "probe-cache.json"
    return Path.home() / ".local" / "state" / "workflow-herdr" / "probe-cache.json"


def cache_ttl_seconds() -> int:
    raw = os.environ.get("WORKFLOW_HERDR_PROBE_TTL")
    if raw in (None, ""):
        return DEFAULT_CACHE_TTL
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_CACHE_TTL


def cache_disabled() -> bool:
    flag = (os.environ.get("WORKFLOW_HERDR_PROBE_FRESH") or "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    return cache_ttl_seconds() == 0


def load_probe_cache() -> dict:
    path = probe_cache_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_probe_cache(data: dict) -> None:
    path = probe_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _cache_get(bucket: str, key: str) -> dict | None:
    if cache_disabled():
        return None
    entry = ((load_probe_cache().get(bucket) or {}).get(key)) or None
    if not isinstance(entry, dict):
        return None
    fetched = entry.get("fetched_at")
    if not isinstance(fetched, (int, float)):
        return None
    if time.time() - fetched >= cache_ttl_seconds():
        return None
    payload = dict(entry)
    payload.pop("fetched_at", None)
    return payload


def _cache_put(bucket: str, key: str, payload: dict) -> None:
    if cache_disabled() or not payload:
        return
    data = load_probe_cache()
    group = dict(data.get(bucket) or {})
    stored = {name: value for name, value in payload.items() if name != "fetched_at"}
    stored["fetched_at"] = time.time()
    group[key] = stored
    data[bucket] = group
    save_probe_cache(data)


def codex_models_cache_path() -> Path | None:
    override = os.environ.get("WORKFLOW_HERDR_CODEX_CACHE") or os.environ.get(
        "CODEX_MODELS_CACHE"
    )
    if override:
        path = Path(override)
        return path if path.is_file() else None
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    path = home / "models_cache.json"
    return path if path.is_file() else None


def parse_codex_models_cache(data: dict | str) -> dict:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    data = data if isinstance(data, dict) else {}
    ids: list[str] = []
    aliases: list[str] = []
    efforts: list[str] = []
    for model in data.get("models") or []:
        if not isinstance(model, dict):
            continue
        visibility = str(model.get("visibility") or "list").lower()
        if visibility in ("hide", "hidden"):
            continue
        slug = model.get("slug") or model.get("id")
        if slug and str(slug) not in ids:
            ids.append(str(slug))
        display = model.get("display_name") or model.get("name")
        if display:
            alias = _norm(str(display))
            if alias and alias not in aliases:
                aliases.append(str(display))
        for level in model.get("supported_reasoning_levels") or []:
            effort = level.get("effort") if isinstance(level, dict) else level
            name = str(effort or "").strip().lower()
            if name in KNOWN_EFFORTS and name not in efforts:
                efforts.append(name)
    return {
        "ids": ids,
        "aliases": aliases,
        "efforts_live": efforts,
        "source": "codex models_cache.json",
        "fetched_at": data.get("fetched_at"),
    }


def load_codex_models_cache() -> dict:
    path = codex_models_cache_path()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    parsed = parse_codex_models_cache(data)
    if not parsed.get("ids"):
        return {}
    return parsed


def parse_herdr_status(text: str) -> dict:
    raw = (text or "").strip()
    data: dict = {}
    if raw.startswith("{"):
        try:
            loaded = json.loads(raw)
            data = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            data = {}
    if not data:
        from yaml_lite import load_yaml

        parsed = load_yaml(raw) if raw else {}
        data = parsed if isinstance(parsed, dict) else {}
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    code = str(error.get("code") or "")
    client = data.get("client") if isinstance(data.get("client"), dict) else {}
    server = data.get("server") if isinstance(data.get("server"), dict) else {}
    update = data.get("update") if isinstance(data.get("update"), dict) else {}
    errors: list[str] = []
    client_proto = client.get("protocol")
    server_proto = server.get("private_protocol")
    compatible = server.get("private_protocol_compatible")
    endpoint = server.get("endpoint_compatible")
    restart = update.get("restart_needed")
    stale = update.get("server_binary_stale")
    server_status = server.get("status")
    lowered = raw.lower()
    if code == "protocol_mismatch" or "protocol_mismatch" in lowered:
        errors.append(
            "Herdr protocol_mismatch: CLI and running server disagree"
        )
    if compatible is False:
        errors.append(
            f"Herdr private protocol incompatible "
            f"(client {client_proto}, server {server_proto})"
        )
    if endpoint is False:
        errors.append("Herdr endpoint_compatible is no")
    if restart is True:
        errors.append("Herdr restart_needed: yes")
    if stale is True:
        errors.append("Herdr server_binary_stale: yes")
    if server_status and str(server_status).lower() not in ("running", "ok", "true"):
        errors.append(f"Herdr server status is {server_status}")
    return {
        "ok": not errors,
        "errors": errors,
        "fix": PROTOCOL_FIX if errors else None,
        "client_protocol": client_proto,
        "server_protocol": server_proto,
        "restart_needed": bool(restart),
        "server_binary_stale": bool(stale),
        "private_protocol_compatible": compatible,
        "endpoint_compatible": endpoint,
        "server_status": server_status,
        "source": "herdr status",
    }


def herdr_protocol(*, run_status=None) -> dict:
    if run_status is not None:
        text = run_status() if callable(run_status) else str(run_status)
        return parse_herdr_status(text)
    from workflow_guard import resolve_command

    herdr_bin = os.environ.get("HERDR_BIN_PATH") or resolve_command("herdr") or "herdr"
    result = run_cli(herdr_bin, ["status"])
    text = result.get("text") or ""
    if not text.strip() and result.get("error"):
        return {
            "ok": False,
            "errors": [f"herdr status failed: {result['error']}"],
            "fix": PROTOCOL_FIX,
            "source": "herdr status",
        }
    parsed = parse_herdr_status(text)
    if result.get("ok") is False and parsed.get("ok") and result.get("error"):
        parsed["ok"] = False
        parsed["errors"] = list(parsed.get("errors") or []) + [
            f"herdr status failed: {result.get('error') or result.get('code')}"
        ]
        parsed["fix"] = PROTOCOL_FIX
    return parsed


def run_cli(executable: str, args: list[str], *, timeout: int = DEFAULT_TIMEOUT, env=None) -> dict:
    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env or os.environ,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "error": f"timed out after {timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "text": "", "error": "executable vanished"}
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    return {"ok": result.returncode == 0, "text": text, "code": result.returncode}


def herdr_kinds(*, run_help=None, use_cache: bool = True) -> dict:
    if run_help is not None:
        text = run_help()
        return {"ok": bool(parse_herdr_kinds(text)), "kinds": parse_herdr_kinds(text), "source": "injected"}
    if use_cache:
        cached = _cache_get("kinds", "herdr")
        if cached and cached.get("kinds"):
            cached["ok"] = bool(cached.get("kinds"))
            cached.setdefault("source", "probe-cache")
            return cached
    from workflow_guard import resolve_command

    herdr_bin = os.environ.get("HERDR_BIN_PATH") or resolve_command("herdr") or "herdr"
    result = run_cli(herdr_bin, ["agent", "start", "--help"])
    kinds = parse_herdr_kinds(result.get("text") or "")
    payload = {
        "ok": bool(kinds),
        "kinds": kinds,
        "source": "herdr agent start --help",
        "error": None if kinds else "could not parse Herdr kinds",
    }
    if use_cache and payload["ok"]:
        _cache_put("kinds", "herdr", payload)
    return payload


def inventory_for(
    harness: str,
    executable: str,
    *,
    run_cli_fn=run_cli,
    harness_yaml: dict | None = None,
    use_cache: bool = True,
) -> dict:
    harness_yaml = harness_yaml or {}
    declared = list(harness_yaml.get("known_models") or [])
    spec = INVENTORY_CMDS.get(harness) or {}
    cache_key = f"{harness}:{executable}"
    if use_cache:
        cached = _cache_get("inventories", cache_key)
        if cached and (cached.get("ids") or cached.get("health") == "ok"):
            cached.setdefault("harness", harness)
            cached.setdefault("executable", executable)
            return cached
    data: dict = {
        "harness": harness,
        "executable": executable,
        "ids": [],
        "aliases": [],
        "efforts_live": [],
        "source": None,
        "health": None,
        "error": None,
    }
    if "models" in spec:
        raw = run_cli_fn(executable, spec["models"])
        if harness == "grok":
            parsed = parse_grok_models(raw.get("text") or "")
        else:
            parsed = parse_devin_models(raw.get("text") or "")
        data["ids"] = parsed.get("ids") or []
        data["aliases"] = parsed.get("aliases") or []
        data["source"] = parsed.get("source")
        if not data["ids"]:
            data["error"] = f"{harness} models inventory is empty"
    if "help" in spec:
        help_raw = run_cli_fn(executable, spec["help"])
        data["efforts_live"] = parse_help_efforts(help_raw.get("text") or "")
    if harness == "codex":
        cached_models = load_codex_models_cache()
        if cached_models.get("ids"):
            data["ids"] = list(cached_models.get("ids") or [])
            data["aliases"] = list(cached_models.get("aliases") or [])
            data["source"] = cached_models.get("source")
            if cached_models.get("efforts_live"):
                data["efforts_live"] = list(cached_models.get("efforts_live") or [])
    if "doctor" in spec:
        try:
            doc = run_cli_fn(executable, spec["doctor"], timeout=DEFAULT_TIMEOUT)
        except TypeError:
            doc = run_cli_fn(executable, spec["doctor"])
        text = doc.get("text") or ""
        if re.search(r"not logged in|unauthenticated|login required", text, re.I):
            data["health"] = "failed"
            data["error"] = data["error"] or f"{harness} is not logged in"
        elif doc.get("error"):
            if data.get("ids"):
                data["health"] = "degraded"
                data["warning"] = f"{harness} doctor: {doc['error']}"
            else:
                data["health"] = "failed"
                data["error"] = data["error"] or f"{harness} doctor: {doc['error']}"
        else:
            data["health"] = "ok"
    if not data["ids"] and declared:
        data["ids"] = declared
        data["source"] = data["source"] or "workflow.yaml known_models"
        data["declared"] = True
    if (
        use_cache
        and (data.get("ids") or data.get("health") in ("ok", "degraded"))
        and data.get("health") != "failed"
    ):
        _cache_put("inventories", cache_key, data)
    return data


def startable_nodes(config: dict, volume: str | None = None) -> list[str]:
    nodes = config.get("nodes") or {}
    if volume:
        graph = (config.get("graphs") or {}).get(volume) or {}
        names = list(graph.get("nodes") or graph.get("seats") or [])
    else:
        names = list(nodes.keys())
    out = []
    for name in names:
        node = nodes.get(name) or {}
        harness = node.get("harness") or node.get("cli")
        if not node.get("start", True) or harness in (None, "human"):
            continue
        if name not in out:
            out.append(name)
    return out


def probe_seats(
    config: dict,
    *,
    volume: str | None = None,
    kinds: list[str] | None = None,
    inventories: dict | None = None,
    run_cli_fn=None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    seats: dict[str, dict] = {}
    from workflow_guard import resolve_command

    kinds = kinds if kinds is not None else herdr_kinds().get("kinds") or []
    if not kinds:
        errors.append("Herdr kind list is empty; cannot confirm --kind")
    computed: dict = dict(inventories) if inventories is not None else {}
    for seat in startable_nodes(config, volume):
        node = (config.get("nodes") or {}).get(seat) or {}
        harness_name = node.get("harness") or node.get("cli")
        harness = (config.get("harnesses") or {}).get(harness_name) or {}
        kind = harness.get("kind")
        model = node.get("model")
        effort = node.get("effort")
        resolved = (
            resolve_command(str(harness_name)) if inventories is None else str(harness_name)
        )
        info = {
            "harness": harness_name,
            "kind": kind,
            "model": model,
            "effort": effort,
            "resolved": resolved,
            "kind_ok": False,
            "model_ok": False,
            "effort_ok": False,
            "fix": None,
        }
        if not resolved:
            errors.append(f"{seat}: no safe executable for {harness_name}")
            info["fix"] = f"Install {harness_name} on PATH as a Windows-native binary (.exe/.cmd), not an npm shim"
            seats[seat] = info
            continue
        if kind and kinds and kind not in kinds:
            errors.append(f"{seat}: Herdr has no kind {kind}")
            info["fix"] = f"Use a kind from: {', '.join(kinds)}"
        elif kind:
            info["kind_ok"] = True
        declared_efforts = list(harness.get("efforts") or [])
        inventory = computed.get(harness_name)
        if inventory is None and inventories is None:
            inventory = inventory_for(
                str(harness_name),
                resolved,
                run_cli_fn=run_cli_fn or run_cli,
                harness_yaml=harness,
            )
            computed[str(harness_name)] = inventory
        inventory = inventory or {}
        info["inventory_source"] = inventory.get("source")
        info["inventory_ids"] = list(inventory.get("ids") or [])[:20]
        live_efforts = [
            item
            for item in (inventory.get("efforts_live") or [])
            if item in KNOWN_EFFORTS or item in declared_efforts
        ]
        allowed_efforts = live_efforts or declared_efforts
        if effort and allowed_efforts and effort not in allowed_efforts:
            errors.append(
                f"{seat}: effort {effort} is not available for {harness_name} "
                f"(have {allowed_efforts})"
            )
            info["fix"] = f"Pick an effort from {allowed_efforts} in .herdr/workflow.yaml"
        elif effort:
            info["effort_ok"] = True
        if model in (None, ""):
            errors.append(f"{seat}: model is missing")
            info["fix"] = f"Set nodes.{seat}.model in workflow YAML"
        elif inventory.get("ids"):
            if model_matches(str(model), inventory, effort):
                info["model_ok"] = True
            else:
                errors.append(
                    f"{seat}: model {model} is not in {harness_name} inventory"
                )
                sample = ", ".join(list(inventory.get("ids") or [])[:8])
                info["fix"] = (
                    f"Change nodes.{seat}.model to a live id (e.g. {sample}) "
                    f"or install access to {model}"
                )
        elif inventory.get("error"):
            errors.append(f"{seat}: {inventory['error']}")
            info["fix"] = f"Run `{harness_name}` and confirm you are logged in"
        else:
            errors.append(
                f"{seat}: cannot confirm model {model}; {harness_name} has no live inventory"
            )
            info["fix"] = (
                f"Add harnesses.{harness_name}.known_models or set "
                "WORKFLOW_HERDR_MODELS_JSON"
            )
        if inventory.get("health") == "failed":
            errors.append(f"{seat}: {harness_name} doctor failed")
            info["fix"] = f"Run `{harness_name} doctor` and fix auth/runtime"
        elif inventory.get("health") == "degraded" or inventory.get("warning"):
            warnings.append(
                f"{seat}: {inventory.get('warning') or (str(harness_name) + ' doctor degraded')}"
            )
        seats[seat] = info
    extra = os.environ.get("WORKFLOW_HERDR_MODELS_JSON")
    if extra:
        try:
            json.loads(extra)
        except json.JSONDecodeError:
            warnings.append("WORKFLOW_HERDR_MODELS_JSON is invalid")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "seats": seats,
        "kinds": kinds,
        "volume": volume,
    }
