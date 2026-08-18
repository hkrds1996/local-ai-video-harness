"""Manifest loading and static validation.

The manifest describes *what* should be produced: title, rendering target,
ordered shots, and optional narration segments. It deliberately contains no
local model paths, credentials, or machine-specific configuration.

Two shapes are accepted:

- **generation**: a non-empty ``shots`` array whose entries carry ``id``,
  ``prompt``, and a duration (``duration`` or the legacy
  ``duration_seconds``);
- **editorial**: ``narration.segments`` whose entries carry ``id``, ``text``,
  and a ``clip`` path pointing at existing media, plus optional timed
  ``cards`` overlays. This shape drives ``run --post-only`` without any GPU
  work.

The two shapes compose: a manifest can list generation ``shots`` and then
reference their outputs from ``narration.segments`` for the postproduction
phase.
"""
from __future__ import annotations

import json
from pathlib import Path

RENDER_KEYS = {"width", "height", "fps"}
SHOT_KEYS = {"id", "prompt"}
SEGMENT_KEYS = {"id", "text"}


def load_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    return value


def shot_duration(shot: dict, default: float = 5.0) -> float:
    value = shot.get("duration", shot.get("duration_seconds", default))
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_manifest(path: Path) -> list[str]:
    project = load_manifest(path)
    errors = []
    if not project.get("title"):
        errors.append("missing project key: title")
    if not (project.get("name") or project.get("slug")):
        errors.append("missing project key: name or slug")

    render = project.get("render")
    if not isinstance(render, dict):
        errors.append("render must be an object")
    else:
        for key in RENDER_KEYS:
            if key not in render:
                errors.append(f"render.{key} is required")

    shots = project.get("shots", [])
    if not isinstance(shots, list):
        errors.append("shots must be a list")
        shots = []
    narration = project.get("narration", {})
    segments = narration.get("segments", []) if isinstance(narration, dict) else []
    if not shots and not segments:
        errors.append("manifest needs shots, narration.segments, or both")

    seen_shots = set()
    for index, shot in enumerate(shots, 1):
        missing = SHOT_KEYS - set(shot)
        if missing:
            errors.append(f"shot {index}: missing keys: {', '.join(sorted(missing))}")
        shot_id = shot.get("id")
        if shot_id in seen_shots:
            errors.append(f"shot {index}: duplicate id {shot_id!r}")
        seen_shots.add(shot_id)
        try:
            if shot_duration(shot) <= 0:
                errors.append(f"shot {index}: duration must be positive")
        except (TypeError, ValueError):
            errors.append(f"shot {index}: duration must be numeric")

    if not isinstance(narration, dict):
        errors.append("narration must be an object")
    elif narration.get("segments") is not None:
        if not isinstance(segments, list):
            errors.append("narration.segments must be a list")
        else:
            seen_segments = set()
            for index, segment in enumerate(segments, 1):
                missing = SEGMENT_KEYS - set(segment)
                if missing:
                    errors.append(
                        f"narration segment {index}: missing keys: {', '.join(sorted(missing))}"
                    )
                segment_id = segment.get("id")
                if segment_id in seen_segments:
                    errors.append(f"narration segment {index}: duplicate id {segment_id!r}")
                seen_segments.add(segment_id)
                if segment.get("cards") is not None and not isinstance(segment.get("cards"), list):
                    errors.append(f"narration segment {index}: cards must be a list")
    return errors
