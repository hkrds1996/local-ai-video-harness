"""Execution layer: backend startup, shot generation, and postproduction.

The runner combines a public project manifest with an untracked local
configuration. For every shot it clones or converts the workflow template,
injects the shot prompt, seed, and duration, submits the job to the local
ComfyUI HTTP API, polls history, downloads the returned media, and persists
state so interrupted runs can resume.

Two top-level modes are supported:

- generation (default): queue shots and concatenate the returned clips;
- postproduction (``--post-only``): synthesize narration with an independent
  TTS provider, render the editorial overlay (titles, source badges, timed
  data cards, subtitles), and compose the final MP4 from existing clips.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import time
from pathlib import Path

from .comfy_api import ComfyClient, clone_workflow, set_input
from .manifest import load_manifest, shot_duration
from .minimax_h3_canvas import convert as convert_h3_canvas


def _start_backend(config: dict, output_dir: Path):
    """Start ComfyUI from the local config; return (process, log_handle) or (None, None)."""
    if config.get("comfy_root"):
        root = Path(config["comfy_root"]).expanduser().resolve()
        script = root / config.get("start_script", "start_h3_low_vram.bat")
        if not script.exists():
            raise FileNotFoundError(script)
        command, cwd = [str(script)], str(root)
        shell = True
    else:
        command = config.get("start_command")
        if not command:
            return None, None
        if not isinstance(command, list) or not command:
            raise ValueError("start_command must be a non-empty JSON array")
        cwd, shell = config.get("start_cwd"), False
    log_path = output_dir / "backend.log"
    log_handle = log_path.open("a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        shell=shell,
    )
    return process, log_handle


def _prepare_workflow(workflow_source: dict, config: dict, shot: dict, seed: int, first_frame_node=None):
    workflow_format = config.get("workflow_format", "auto")
    is_canvas = workflow_format == "canvas" or (
        workflow_format == "auto" and "nodes" in workflow_source and "definitions" in workflow_source
    )
    duration = shot_duration(shot, float(config.get("default_duration", 5)))
    if is_canvas:
        job = convert_h3_canvas(
            workflow_source,
            prompt=shot["prompt"],
            duration=duration,
            seed=seed,
            first_frame_node=first_frame_node,
        )
        for node in job.values():
            if node.get("class_type") == "SaveVideo":
                node["inputs"]["filename_prefix"] = shot["id"]
        return job
    job = clone_workflow(workflow_source)
    set_input(job, config["prompt_node"], config.get("prompt_input", "text"), shot["prompt"])
    set_input(job, config["seed_node"], config.get("seed_input", "seed"), seed)
    return job


def _extract_last_frame(video: Path, frame: Path) -> None:
    """Extract the final frame, preferring ffmpeg with a PyAV fallback."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        result = subprocess.run(
            [ffmpeg, "-y", "-sseof", "-0.1", "-i", str(video), "-frames:v", "1", str(frame)],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and frame.exists():
            return
    from .media import extract_last_frame as pyav_last_frame
    pyav_last_frame(video, frame)


def _concat(output: Path, files: list[Path]) -> None:
    """Concatenate generated shots with ffmpeg when available, PyAV otherwise."""
    if not files:
        return
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        concat_list = output.parent / "concat.txt"
        concat_list.write_text(
            "\n".join("file '" + str(p).replace("'", "'\\''") + "'" for p in files),
            encoding="utf-8",
        )
        result = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(output)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        result = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        raise RuntimeError(result.stderr[-3000:])
    from .media import concat_videos
    concat_videos(files, output)


def run_postproduction(project_path: Path, project: dict, output_dir: Path, config: dict, force_tts: bool):
    """Synthesize narration and compose the final editorial video from clips."""
    narration = project.get("narration")
    if not narration or not narration.get("segments"):
        raise ValueError("postproduction requires narration.segments in the project manifest")
    from .narration import generate_timeline
    narration_dir = output_dir / "narration"
    narration_dir.mkdir(parents=True, exist_ok=True)
    print("Generating independent narration...")
    timeline = generate_timeline(
        project,
        narration_dir,
        provider=narration.get("provider", "edge"),
        voice=narration.get("voice"),
        rate=narration.get("rate"),
        pitch=narration.get("pitch"),
        force=force_tts,
    )
    from .editorial import compose
    final_output = output_dir / project.get("render", {}).get("final_output", "final-editorial.mp4")
    print("Composing clips, titles, cards, subtitles, and narration...")
    compose(project_path, timeline, final_output)
    return final_output


def run(project_path: Path, config_path: Path, dry_run: bool = False, resume: bool = False,
        post_only: bool = False, force_tts: bool = False):
    project = load_manifest(project_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    workflow_path = Path(config["workflow_api"])
    out_dir = Path(project.get("output_dir", config.get("output_dir", "generated")))
    if not out_dir.is_absolute():
        out_dir = project_path.parent / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if post_only:
        if dry_run:
            print(f"Post-only project: {project.get('title', project_path.stem)}")
            print(f"Narration segments: {len(project.get('narration', {}).get('segments', []))}")
            return out_dir
        final_output = run_postproduction(project_path, project, out_dir, config, force_tts)
        print(f"Done: {final_output}")
        return out_dir

    shots = project.get("shots", [])
    if not shots:
        raise ValueError("manifest has no shots; run with --post-only to compose existing clips")
    if dry_run:
        print(f"Project: {project.get('title', project_path.stem)}")
        print(f"Workflow: {workflow_path}")
        print(f"Workflow exists: {workflow_path.exists()}")
        print(f"Shots: {len(shots)}")
        for index, shot in enumerate(shots, 1):
            print(f"  {index:02d} {shot.get('id', index)}: {shot['prompt'][:100]}")
        return out_dir

    workflow_source = json.loads(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(workflow_source, dict) or not workflow_source:
        raise ValueError("workflow_api must be a non-empty ComfyUI API-format JSON object")

    server = config.get("server_url", "http://127.0.0.1:8188")
    client = ComfyClient(server, int(config.get("timeout_seconds", 3600)), float(config.get("poll_seconds", 2)))
    backend_process = None
    backend_log = None
    try:
        try:
            client.wait_until_ready(seconds=3)
            print("Local backend is already running")
        except TimeoutError:
            print("Starting local backend")
            backend_process, backend_log = _start_backend(config, out_dir)
            if backend_process is None:
                raise RuntimeError("Backend is not ready and no start command is configured")
            client.wait_until_ready(seconds=int(config.get("startup_timeout_seconds", 240)))

        state_path = out_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"shots": {}}
        metrics_path = out_dir / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {"shots": {}}
        run_started = time.time()
        metrics["last_run_started_at_epoch"] = run_started

        rendered = []
        for index, shot in enumerate(shots, 1):
            shot_id = str(shot.get("id", f"shot-{index:02d}"))
            previous = state["shots"].get(shot_id, {})
            if resume and previous.get("files") and all(Path(item).exists() for item in previous["files"]):
                print(f"[{index}/{len(shots)}] resume {shot_id}")
                metrics["shots"].setdefault(shot_id, {})["resumed_last_run"] = True
                rendered.extend(Path(item) for item in previous["files"])
                continue

            started = time.perf_counter()
            seed = int(shot.get("seed", random.randint(0, 2**31 - 1)))
            first_frame_node = None
            if index > 1 and shot.get("first_frame_from_previous", False):
                previous_files = state["shots"].get(str(shots[index - 2].get("id", f"shot-{index-1:02d}")), {}).get("files", [])
                if not previous_files:
                    raise RuntimeError(f"No previous output found for continuity chaining before {shot_id}")
                tail = out_dir / f"{index - 1:02d}_{shot_id}_previous_last_frame.png"
                _extract_last_frame(Path(previous_files[0]), tail)
                first_frame_node = client.upload_image(tail)
            job = _prepare_workflow(workflow_source, config, shot, seed, first_frame_node)
            workflow_snapshot = out_dir / f"{index:02d}_{shot_id}.workflow.json"
            workflow_snapshot.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{index}/{len(shots)}] submit {shot_id}")
            prompt_id = client.submit(job)
            history = client.wait_for_history(prompt_id)
            files = []
            for output_index, item in enumerate(client.output_items(history), 1):
                suffix = Path(item["filename"]).suffix or ".bin"
                destination = out_dir / f"{index:02d}_{shot_id}_{output_index}{suffix}"
                client.download(item, destination)
                files.append(str(destination.resolve()))
            if not files:
                raise RuntimeError(f"ComfyUI completed {shot_id} but returned no media outputs")
            elapsed = time.perf_counter() - started
            state["shots"][shot_id] = {
                "prompt_id": prompt_id,
                "files": files,
                "seed": seed,
                "prompt": shot["prompt"],
                "duration_seconds": shot_duration(shot),
            }
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            metrics["shots"][shot_id] = {
                "generation_seconds": round(elapsed, 3),
                "resumed_last_run": False,
            }
            rendered.extend(Path(item) for item in files)
            print(f"[{index}/{len(shots)}] complete {shot_id} in {elapsed:.1f}s")

        metrics["last_run_finished_at_epoch"] = time.time()
        metrics["last_run_total_seconds"] = round(metrics["last_run_finished_at_epoch"] - run_started, 3)
        metrics["generation_total_seconds"] = round(
            sum(float(item.get("generation_seconds", 0)) for item in metrics["shots"].values()), 3
        )
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        video_output = out_dir / "shots.mp4"
        _concat(video_output, rendered)
        print(f"Done: {video_output}")
        return out_dir
    finally:
        if backend_process is not None and (config.get("stop_backend_on_exit") or config.get("stop_comfy_on_exit")):
            backend_process.terminate()
        if backend_log is not None:
            backend_log.close()
