from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


ConfigPath = str | tuple[str, ...]


def required_value(data: Mapping[str, Any], path: ConfigPath) -> Any:
    current: Any = data
    for part in _path_parts(path):
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"{_display_path(path)} is required")
        current = current[part]
    return current


def required_mapping(data: Mapping[str, Any], path: ConfigPath) -> Mapping[str, Any]:
    value = required_value(data, path)
    if not isinstance(value, Mapping):
        raise ValueError(f"{_display_path(path)} must be a mapping")
    return value


def required_non_empty_mapping(data: Mapping[str, Any], path: ConfigPath) -> Mapping[str, Any]:
    value = required_mapping(data, path)
    if not value:
        raise ValueError(f"{_display_path(path)} must contain at least one {singular_name(path)}")
    return value


def required_string(data: Mapping[str, Any], path: ConfigPath) -> str:
    value = required_value(data, path)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{_display_path(path)} must be a non-empty string")
    return value.strip()


def required_bool(data: Mapping[str, Any], path: ConfigPath) -> bool:
    value = required_value(data, path)
    if not isinstance(value, bool):
        raise ValueError(f"{_display_path(path)} must be a boolean")
    return value


def required_int(data: Mapping[str, Any], path: ConfigPath, *, minimum: int | None = None) -> int:
    value = required_value(data, path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{_display_path(path)} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{_display_path(path)} must be at least {minimum}")
    return value


def required_optional_int(data: Mapping[str, Any], path: ConfigPath, *, minimum: int | None = None) -> int | None:
    value = required_value(data, path)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{_display_path(path)} must be an integer or null")
    if minimum is not None and value < minimum:
        raise ValueError(f"{_display_path(path)} must be at least {minimum}")
    return value


def required_float(data: Mapping[str, Any], path: ConfigPath, *, minimum: float | None = None) -> float:
    value = required_value(data, path)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{_display_path(path)} must be a number")
    converted = float(value)
    if minimum is not None and converted < minimum:
        raise ValueError(f"{_display_path(path)} must be at least {minimum:g}")
    return converted


def required_string_tuple(data: Mapping[str, Any], path: ConfigPath) -> tuple[str, ...]:
    value = required_value(data, path)
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{_display_path(path)} must be a list of strings")
    if not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{_display_path(path)} must be a non-empty list of strings")
    return tuple(item.strip().lower() for item in value)


def singular_name(path: ConfigPath) -> str:
    name = _path_parts(path)[-1]
    return name[:-1] if name.endswith("s") else "entry"


def _path_parts(path: ConfigPath) -> tuple[str, ...]:
    return tuple(path.split(".")) if isinstance(path, str) else path


def _display_path(path: ConfigPath) -> str:
    return ".".join(_path_parts(path))
