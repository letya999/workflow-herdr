"""Load and write run files: identity, binding, orchestration, artifacts, tasks."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from load_config import expand_layout, resolve
from yaml_lite import dump_yaml, load_yaml


def now_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def index_path() -> Path:
    override = os.environ.get("WORKFLOW_HERDR_INDEX")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "workflow-herdr" / "index.yaml"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "workflow-herdr" / "index.yaml"
    return Path.home() / ".local" / "state" / "workflow-herdr" / "index.yaml"


def paths_for(project: Path, change: str, config: dict | None = None) -> dict[str, Path]:
    config = config or resolve(project)
    rel = expand_layout(config, change=change)
    root = project.resolve()
    return {key: root / value for key, value in rel.items()}


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = load_yaml(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(dump_yaml(data), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_identity(project: Path, change: str, config: dict | None = None) -> dict:
    return _read_yaml(paths_for(project, change, config)["identity"])


def save_identity(project: Path, change: str, data: dict, config: dict | None = None) -> None:
    _write_yaml(paths_for(project, change, config)["identity"], data)


def load_binding(project: Path, change: str, config: dict | None = None) -> dict:
    return _read_json(paths_for(project, change, config)["session"])


def save_binding(project: Path, change: str, data: dict, config: dict | None = None) -> None:
    _write_json(paths_for(project, change, config)["session"], data)


def load_orchestration(project: Path, change: str, config: dict | None = None) -> dict:
    return _read_yaml(paths_for(project, change, config)["orchestration"])


def save_orchestration(
    project: Path, change: str, data: dict, config: dict | None = None
) -> None:
    _write_yaml(paths_for(project, change, config)["orchestration"], data)


def load_artifacts(project: Path, change: str, config: dict | None = None) -> dict:
    return _read_yaml(paths_for(project, change, config)["artifacts"])


def save_artifacts(project: Path, change: str, data: dict, config: dict | None = None) -> None:
    _write_yaml(paths_for(project, change, config)["artifacts"], data)


def load_tasks(project: Path, change: str, config: dict | None = None) -> dict:
    files = paths_for(project, change, config)
    path = files["state"]
    if not path.is_file():
        legacy = files["change_dir"] / "state.yaml"
        if legacy.is_file():
            path = legacy
    data = _read_yaml(path)
    data.setdefault("tasks", [])
    data.setdefault("workstreams", [])
    data.setdefault("sizing", {})
    return data


def save_tasks(project: Path, change: str, data: dict, config: dict | None = None) -> None:
    _write_yaml(paths_for(project, change, config)["state"], data)


def bump(data: dict, writer: str) -> dict:
    data["revision"] = int(data.get("revision") or 0) + 1
    data["updated_at"] = now_stamp()
    data["updated_by"] = writer
    return data


def load_index(path: Path | None = None) -> dict:
    target = path or index_path()
    data = _read_yaml(target)
    data.setdefault("runs", [])
    return data


def save_index(data: dict, path: Path | None = None) -> None:
    _write_yaml(path or index_path(), data)


def upsert_index_run(entry: dict, path: Path | None = None) -> dict:
    data = load_index(path)
    runs = data.setdefault("runs", [])
    updated = False
    for index, item in enumerate(runs):
        if (
            _same_project(item.get("project"), entry.get("project"))
            and item.get("change") == entry.get("change")
            and item.get("herdr_session") == entry.get("herdr_session")
        ):
            runs[index] = {**item, **entry}
            updated = True
            break
    if not updated:
        runs.append(entry)
    save_index(data, path)
    return data


def _same_project(left, right) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    try:
        return Path(str(left)).resolve() == Path(str(right)).resolve()
    except Exception:
        return False


def find_active_run(
    project: str, herdr_session: str, path: Path | None = None
) -> dict | None:
    for item in load_index(path).get("runs") or []:
        if (
            _same_project(item.get("project"), project)
            and item.get("herdr_session") == herdr_session
            and item.get("status") == "active"
        ):
            return item
    return None
