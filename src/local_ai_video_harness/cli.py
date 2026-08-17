from __future__ import annotations

import argparse
import json
from pathlib import Path

from .manifest import load_manifest, validate_manifest
from .runner import run


def plan(path: Path) -> int:
    project = load_manifest(path)
    total = sum(float(shot["duration_seconds"]) for shot in project["shots"])
    print(f"Project: {project['title']}")
    print(f"Shots: {len(project['shots'])}")
    print(f"Planned video duration: {total:.1f}s")
    print(f"Render: {project['render']['width']}x{project['render']['height']} @ {project['render']['fps']}fps")
    for index, shot in enumerate(project["shots"], 1):
        print(f"  {index:02d} {shot['id']}: {shot['duration_seconds']}s")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate and inspect local AI video manifests")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "plan"):
        item = sub.add_parser(command)
        item.add_argument("--manifest", required=True, type=Path)
    execute = sub.add_parser("run")
    execute.add_argument("--manifest", required=True, type=Path)
    execute.add_argument("--config", required=True, type=Path)
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
        run(args.manifest, args.config)
        return 0
    return plan(args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
