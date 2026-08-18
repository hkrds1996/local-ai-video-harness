"""Static continuity checks for chained H3-style shots.

Short text-to-video models produce a few seconds per shot. Visual continuity
across shots depends on the manifest: prompts should share subject and style
anchors, chained shots should inherit the previous shot's last frame, and
durations should stay inside the model's limit. This module turns those rules
into a JSON report that can gate a run before expensive generation starts.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def media_duration(path: Path, ffprobe: str):
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def check_project(project_path: Path, media_dir: Path = None, max_seconds: float = 15.0) -> dict:
    """Validate shot durations, prompt anchors, and chaining flags."""
    project = load(project_path)
    shots = project.get("shots", [])
    errors, warnings, checks = [], [], []
    if not project.get("style_anchor"):
        warnings.append("project.style_anchor is missing; every shot may drift stylistically")

    previous_words = None
    for index, shot in enumerate(shots, 1):
        shot_id = str(shot.get("id", f"shot-{index:02d}"))
        duration = float(shot.get("duration", shot.get("duration_seconds", project.get("default_duration", 5))))
        prompt = shot.get("prompt", "")
        if duration > max_seconds:
            errors.append(f"{shot_id}: duration {duration}s exceeds the {max_seconds}s maximum")
        if not prompt.strip():
            errors.append(f"{shot_id}: empty prompt")
        if index > 1:
            overlap = len(words(prompt) & previous_words) / max(1, len(words(prompt) | previous_words))
            if overlap < 0.04:
                warnings.append(
                    f"{shot_id}: very low prompt overlap with the previous shot ({overlap:.1%}); "
                    "add shared subject/style anchors"
                )
        if index > 1 and not shot.get("first_frame_from_previous", False):
            warnings.append(f"{shot_id}: no first_frame_from_previous flag; visual continuity may jump")
        checks.append({"id": shot_id, "duration": duration, "has_prompt": bool(prompt.strip())})
        previous_words = words(prompt)

    media = []
    if media_dir and media_dir.exists():
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            warnings.append("ffprobe not found; generated media durations were not inspected")
        else:
            for path in sorted(media_dir.glob("*.mp4")):
                duration = media_duration(path, ffprobe)
                media.append({"file": str(path), "duration": duration})
                if duration is not None and duration > max_seconds + 0.25:
                    warnings.append(f"{path.name}: media duration {duration:.2f}s exceeds the target")

    return {
        "project": project.get("title", project_path.stem),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "shots": checks,
        "media": media,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate H3 shot duration and narrative continuity")
    parser.add_argument("project", type=Path)
    parser.add_argument("--media-dir", type=Path)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = check_project(args.project, args.media_dir, args.max_seconds)
    report_path = args.report or args.project.with_name("continuity_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
