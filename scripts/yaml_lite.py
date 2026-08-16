"""Minimal YAML subset: mappings, lists, scalars, comments. No tags or anchors."""

from __future__ import annotations

from typing import Any


def load_yaml(text: str) -> Any:
    lines = []
    for raw in text.splitlines():
        if (not raw.strip()) or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))
    value, _ = _parse_block(lines, 0, 0)
    return value


def _parse_block(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[Any, int]:
    if index >= len(lines):
        return None, index
    _, content = lines[index]
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_map(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"bad indent at {content!r}")
        if content.startswith("- "):
            break
        key, sep, rest = content.partition(":")
        if not sep:
            raise ValueError(f"expected mapping line: {content!r}")
        key = key.strip()
        rest = rest.strip()
        index += 1
        if rest in ("", "|", ">"):
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                result[key] = child
            else:
                result[key] = None
        else:
            result[key] = _scalar(rest)
    return result, index


def _parse_list(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"bad list indent at {content!r}")
        if not content.startswith("- "):
            break
        rest = content[2:].strip()
        index += 1
        if rest == "" or rest == ":" or (":" in rest and rest.endswith(":")):
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                result.append(child)
            else:
                result.append(None)
        elif rest.startswith("{") or ":" not in rest:
            result.append(_scalar(rest))
        else:
            item, leftover = _parse_inline_map_or_scalar(rest)
            if leftover is None:
                if index < len(lines) and lines[index][0] > indent:
                    nested, index = _parse_block(lines, index, lines[index][0])
                    if isinstance(item, dict) and isinstance(nested, dict):
                        item.update(nested)
                result.append(item)
            else:
                result.append(item)
    return result, index


def _parse_inline_map_or_scalar(text: str) -> tuple[Any, None]:
    key, sep, rest = text.partition(":")
    if not sep:
        return _scalar(text), None
    value = rest.strip()
    if value:
        return {key.strip(): _scalar(value)}, None
    return {key.strip(): None}, None


def _scalar(text: str) -> Any:
    if text in ("null", "~", "Null"):
        return None
    if text == "[]":
        return []
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part.strip()) for part in inner.split(",") if part.strip()]
    if text == "{}":
        return {}
    if text in ("true", "True", "on", "On", "yes", "Yes"):
        return True
    if text in ("false", "False", "off", "Off", "no", "No"):
        return False
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    try:
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
    except ValueError:
        pass
    return text


def dump_yaml(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                if not item:
                    rendered = "{}" if isinstance(item, dict) else "[]"
                    lines.append(f"{pad}{key}: {rendered}")
                else:
                    lines.append(f"{pad}{key}:")
                    lines.append(dump_yaml(item, indent + 1).rstrip("\n"))
            else:
                lines.append(f"{pad}{key}: {_dump_scalar(item)}")
        return "\n".join(lines) + "\n"
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, child in item.items():
                    prefix = "- " if first else "  "
                    first = False
                    if isinstance(child, (dict, list)) and child:
                        lines.append(f"{pad}{prefix}{key}:")
                        lines.append(dump_yaml(child, indent + 2).rstrip("\n"))
                    else:
                        shown = (
                            "{}"
                            if child == {}
                            else ("[]" if child == [] else _dump_scalar(child))
                        )
                        if isinstance(child, (dict, list)) and not child:
                            lines.append(f"{pad}{prefix}{key}: {shown}")
                        else:
                            lines.append(f"{pad}{prefix}{key}: {shown}")
            else:
                lines.append(f"{pad}- {_dump_scalar(item)}")
        return "\n".join(lines) + "\n"
    return _dump_scalar(value) + "\n"


def _dump_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    text = str(value)
    if text == "" or any(ch in text for ch in [":", "#", "\n"]):
        return json_quote(text)
    return text


def json_quote(text: str) -> str:
    return (
        '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    )


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = deep_merge(base[key], value) if key in base else value
        return out
    return override
