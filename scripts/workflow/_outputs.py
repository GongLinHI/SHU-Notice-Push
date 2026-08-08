from __future__ import annotations

from pathlib import Path
from typing import Mapping


def append_github_outputs(path: Path | None, values: Mapping[str, str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")
