"""Execution layer: backend startup, shot generation, and postproduction.

The runner combines a public project manifest with an untracked local
configuration. Two classes own the two top-level phases:

- :class:`GenerationRunner` queues shots on the local ComfyUI HTTP API,
  downloads media, persists state so interrupted runs resume, and
  concatenates the clips;
- :class:`PostproductionRunner` synthesizes narration with an independent
  TTS provider and composes the final editorial MP4 from existing clips.

``run()`` is the dispatch entry used by the CLI. It also honors the legacy
``postproduction.enabled`` config switch by running postproduction after
generation, matching the behaviour of earlier versions.
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
        resolution = config.get("resolution", [1344, 768])
        job = convert_h3_canvas(
            workflow_source,
            prompt=shot["prompt"],
            duration=duration,
            seed=seed,
            first_frame_node=first_frame_node,
            width=int(resolution[0]),
            height=int(resolution[1]),
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


class GenerationRunner:
    """Queue shots, download outputs, and concatenate them into one clip."""

    def __init__(self, project: dict, config: dict, out_dir: Path, resume: bool = False):
        self.project = project
        self.config = config
        self.out_dir = out_dir
        self.resume = resume
        self.state_path = out_dir / "state.json"
        self.metrics_path = out_dir / "metrics.json"

    def _load_state(self) -> dict:
        state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {"shots": {}}
        metrics = json.loads(self.metrics_path.read_text(encoding="utf-8")) if self.metrics_path.exists() else {"shots": {}}
        return state, metrics

    def prepare_backend(self) -> tuple[ComfyClient, object, object]:
        """Return (client, backend_process, log_handle); the process may be None."""
        server = self.config.get("server_url", "http://127.0.0.1:8188")
        client = ComfyClient(server, int(self.config.get("timeout_seconds", 3600)), float(self.config.get("poll_seconds", 2)))
        try:
            client.wait_until_ready(seconds=3)
            print("Local backend is already running")
            return client, None, None
        except TimeoutError:
            print("Starting local backend")
            process, log = _start_backend(self.config, self.out_dir)
            if process is None:
                raise RuntimeError("Backend is not ready and no start command is configured")
            client.wait_until_ready(seconds=int(self.config.get("startup_timeout_seconds", 240)))
            return client, process, log

    def generate(self, client: ComfyClient, workflow_source: dict) -> list[Path]:
        """Submit every shot and return the downloaded clip paths."""
        shots = self.project["shots"]
        state, metrics = self._load_state()
        run_started = time.time()
        metrics["last_run_started_at_epoch"] = run_started
        rendered: list[Path] = []

        for index, shot in enumerate(shots, 1):
            shot_id = str(shot.get("id", f"shot-{index:02d}"))
            previous = state["shots"].get(shot_id, {})
            if self.resume and previous.get("files") and all(Path(item).exists() for item in previous["files"]):
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
                tail = self.out_dir / f"{index - 1:02d}_{shot_id}_previous_last_frame.png"
                _extract_last_frame(Path(previous_files[0]), tail)
                first_frame_node = client.upload_image(tail)
            job = _prepare_workflow(workflow_source, self.config, shot, seed, first_frame_node)
            workflow_snapshot = self.out_dir / f"{index:02d}_{shot_id}.workflow.json"
            workflow_snapshot.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{index}/{len(shots)}] submit {shot_id}")
            prompt_id = client.submit(job)
            history = client.wait_for_history(prompt_id)
            files = []
            for output_index, item in enumerate(client.output_items(history), 1):
                suffix = Path(item["filename"]).suffix or ".bin"
                destination = self.out_dir / f"{index:02d}_{shot_id}_{output_index}{suffix}"
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
            self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            metrics["shots"][shot_id] = {"generation_seconds": round(elapsed, 3), "resumed_last_run": False}
            rendered.extend(Path(item) for item in files)
            print(f"[{index}/{len(shots)}] complete {shot_id} in {elapsed:.1f}s")

        metrics["last_run_finished_at_epoch"] = time.time()
        metrics["last_run_total_seconds"] = round(metrics["last_run_finished_at_epoch"] - run_started, 3)
        metrics["generation_total_seconds"] = round(
            sum(float(item.get("generation_seconds", 0)) for item in metrics["shots"].values()), 3
        )
        self.metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        return rendered

    def finalize(self, rendered: list[Path]) -> Path:
        video_output = self.out_dir / "shots.mp4"
        _concat(video_output, rendered)
        return video_output


class PostproductionRunner:
    """Synthesize narration and compose the final editorial video from clips."""

    def __init__(self, project_path: Path, project: dict, config: dict, out_dir: Path, force_tts: bool = False):
        self.project_path = project_path
        self.project = project
        self.config = config
        self.out_dir = out_dir
        self.force_tts = force_tts

    def run(self) -> Path:
        narration = self.project.get("narration")
        if not narration or not narration.get("segments"):
            raise ValueError("postproduction requires narration.segments in the project manifest")
        from .narration import generate_timeline
        narration_dir = self.out_dir / "narration"
        narration_dir.mkdir(parents=True, exist_ok=True)
        print("Generating independent narration...")
        timeline = generate_timeline(
            self.project,
            narration_dir,
            provider=narration.get("provider", "edge"),
            voice=narration.get("voice"),
            rate=narration.get("rate"),
            pitch=narration.get("pitch"),
            force=self.force_tts,
            cosyvoice=self.config.get("cosyvoice"),
        )
        from .editorial import compose
        final_output = self.out_dir / self.project.get("render", {}).get("final_output", "final-editorial.mp4")
        print("Composing clips, titles, cards, subtitles, and narration...")
        compose(self.project_path, timeline, final_output)
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
        final_output = PostproductionRunner(project_path, project, config, out_dir, force_tts).run()
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

    generation = GenerationRunner(project, config, out_dir, resume)
    client, backend_process, backend_log = generation.prepare_backend()
    try:
        rendered = generation.generate(client, workflow_source)
        video_output = generation.finalize(rendered)
        print(f"Done: {video_output}")
        post = config.get("postproduction", {})
        if post.get("enabled"):
            final_output = PostproductionRunner(project_path, project, config, out_dir, force_tts).run()
            print(f"Final video: {final_output}")
        return out_dir
    finally:
        if backend_process is not None and (config.get("stop_backend_on_exit") or config.get("stop_comfy_on_exit")):
            backend_process.terminate()
        if backend_log is not None:
            backend_log.close()
