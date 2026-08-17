from __future__ import annotations

import json
from pathlib import Path


REQUIRED_PROJECT_KEYS = {"name", "title", "render", "shots"}
REQUIRED_SHOT_KEYS = {"id", "prompt", "duration_seconds"}


def load_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    return value


def validate_manifest(path: Path) -> list[str]:
    project = load_manifest(path)
    errors = []
    missing = REQUIRED_PROJECT_KEYS - set(project)
    if missing:
        errors.append(f"missing project keys: {', '.join(sorted(missing))}")
    render = project.get("render", {})
    for key in ("width", "height", "fps"):
        if key not in render:
            errors.append(f"render.{key} is required")
    shots = project.get("shots", [])
    if not isinstance(shots, list) or not shots:
        errors.append("shots must be a non-empty list")
    seen = set()
    for index, shot in enumerate(shots, 1):
        missing = REQUIRED_SHOT_KEYS - set(shot)
        if missing:
            errors.append(f"shot {index}: missing keys: {', '.join(sorted(missing))}")
        shot_id = shot.get("id")
        if shot_id in seen:
            errors.append(f"shot {index}: duplicate id {shot_id!r}")
        seen.add(shot_id)
        try:
            if float(shot.get("duration_seconds", 0)) <= 0:
                errors.append(f"shot {index}: duration_seconds must be positive")
        except (TypeError, ValueError):
            errors.append(f"shot {index}: duration_seconds must be numeric")
    return errors
