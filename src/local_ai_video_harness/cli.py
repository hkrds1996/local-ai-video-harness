"""Command-line interface for validate, plan, check, and run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .continuity import check_project
from .manifest import load_manifest, shot_duration, validate_manifest
from .runner import run


def plan(path: Path) -> int:
    project = load_manifest(path)
    shots = project.get("shots", [])
    segments = project.get("narration", {}).get("segments", [])
    total = sum(shot_duration(shot) for shot in shots)
    print(f"Project: {project['title']}")
    print(f"Shots: {len(shots)}")
    if segments:
        print(f"Narration segments: {len(segments)}")
    if shots:
        print(f"Planned generation duration: {total:.1f}s")
    render = project["render"]
    print(f"Render: {render['width']}x{render['height']} @ {render['fps']}fps")
    for index, shot in enumerate(shots, 1):
        print(f"  {index:02d} {shot['id']}: {shot_duration(shot)}s")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate, plan, and run local AI video manifests")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "plan"):
        item = sub.add_parser(command)
        item.add_argument("--manifest", required=True, type=Path)
    check = sub.add_parser("check", help="Run static shot-continuity checks and write a JSON report")
    check.add_argument("--manifest", required=True, type=Path)
    check.add_argument("--media-dir", type=Path)
    check.add_argument("--max-seconds", type=float, default=15.0)
    check.add_argument("--report", type=Path)
    execute = sub.add_parser("run")
    execute.add_argument("--manifest", required=True, type=Path)
    execute.add_argument("--config", required=True, type=Path)
    execute.add_argument("--dry-run", action="store_true", help="Print the plan without contacting the backend")
    execute.add_argument("--resume", action="store_true", help="Skip shots whose recorded outputs still exist")
    execute.add_argument("--post-only", action="store_true", help="Skip generation; build narration and the final editorial video from existing clips")
    execute.add_argument("--force-tts", action="store_true", help="Regenerate narration audio and subtitles even when cached files exist")
    args = parser.parse_args(argv)
    errors = validate_manifest(args.manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if args.command == "validate":
        print(f"Valid manifest: {args.manifest}")
        return 0
    if args.command == "run":
        run(
            args.manifest,
            args.config,
            dry_run=args.dry_run,
            resume=args.resume,
            post_only=args.post_only,
            force_tts=args.force_tts,
        )
        return 0
    if args.command == "check":
        report = check_project(args.manifest, args.media_dir, args.max_seconds)
        report_path = args.report or args.manifest.with_name("continuity_report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 2
    return plan(args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
