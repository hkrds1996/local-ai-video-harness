from __future__ import annotations

import json
import random
import subprocess
import time
from pathlib import Path

from .comfy_api import ComfyClient, clone_workflow, set_input
from .manifest import load_manifest
from .minimax_h3_canvas import convert as convert_h3_canvas


def _start_backend(config: dict, output_dir: Path):
    command = config.get("start_command")
    if not command:
        return None, None
    if not isinstance(command, list) or not command:
        raise ValueError("start_command must be a non-empty JSON array")
    cwd = config.get("start_cwd")
    log_path = output_dir / "backend.log"
    log_handle = log_path.open("a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    return process, log_handle


def _prepare_workflow(workflow_source: dict, config: dict, shot: dict, seed: int):
    workflow_format = config.get("workflow_format", "auto")
    is_canvas = workflow_format == "canvas" or (
        workflow_format == "auto" and "nodes" in workflow_source and "definitions" in workflow_source
    )
    if is_canvas:
        job = convert_h3_canvas(
            workflow_source,
            prompt=shot["prompt"],
            duration=float(shot["duration_seconds"]),
            seed=seed,
        )
        for node in job.values():
            if node.get("class_type") == "SaveVideo":
                node["inputs"]["filename_prefix"] = shot["id"]
        return job

    job = clone_workflow(workflow_source)
    set_input(job, config["prompt_node"], config.get("prompt_input", "text"), shot["prompt"])
    set_input(job, config["seed_node"], config.get("seed_input", "seed"), seed)
    return job


def run(project_path: Path, config_path: Path):
    project = load_manifest(project_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    workflow_path = Path(config["workflow_api"])
    workflow_source = json.loads(workflow_path.read_text(encoding="utf-8"))
    output_dir = Path(config.get("output_dir", "outputs"))
    if not output_dir.is_absolute():
        output_dir = project_path.parent / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    client = ComfyClient(
        config["server_url"],
        int(config.get("timeout_seconds", 3600)),
        float(config.get("poll_seconds", 2)),
    )
    backend_process = None
    backend_log = None
    try:
        try:
            client.wait_until_ready(seconds=3)
            print("Local backend is already running")
        except TimeoutError:
            print("Starting local backend")
            backend_process, backend_log = _start_backend(config, output_dir)
            if backend_process is None:
                raise RuntimeError("Backend is not ready and start_command is not configured")
            client.wait_until_ready(seconds=int(config.get("startup_timeout_seconds", 240)))

        state_path = output_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"shots": {}}
        metrics = {"started_at_epoch": time.time(), "shots": {}}

        for index, shot in enumerate(project["shots"], 1):
            shot_id = shot["id"]
            previous = state["shots"].get(shot_id, {})
            if previous.get("files") and all(Path(item).exists() for item in previous["files"]):
                print(f"[{index}/{len(project['shots'])}] resume {shot_id}")
                metrics["shots"][shot_id] = {"resumed": True, "seconds": 0}
                continue

            started = time.perf_counter()
            seed = int(shot.get("seed", random.randint(0, 2**31 - 1)))
            job = _prepare_workflow(workflow_source, config, shot, seed)
            workflow_snapshot = output_dir / f"{index:02d}_{shot_id}.workflow.json"
            workflow_snapshot.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{index}/{len(project['shots'])}] submit {shot_id}")
            prompt_id = client.submit(job)
            history = client.wait_for_history(prompt_id)
            files = []
            for output_index, item in enumerate(client.output_items(history), 1):
                suffix = Path(item["filename"]).suffix or ".bin"
                destination = output_dir / f"{index:02d}_{shot_id}_{output_index}{suffix}"
                client.download(item, destination)
                files.append(str(destination.resolve()))
            if not files:
                raise RuntimeError(f"No outputs returned for shot {shot_id}")
            elapsed = time.perf_counter() - started
            state["shots"][shot_id] = {
                "prompt_id": prompt_id,
                "files": files,
                "seed": seed,
                "prompt": shot["prompt"],
                "duration_seconds": shot["duration_seconds"],
            }
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            metrics["shots"][shot_id] = {"resumed": False, "seconds": round(elapsed, 3)}
            print(f"[{index}/{len(project['shots'])}] complete {shot_id} in {elapsed:.1f}s")

        metrics["finished_at_epoch"] = time.time()
        metrics["total_seconds"] = round(metrics["finished_at_epoch"] - metrics["started_at_epoch"], 3)
        (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        post = config.get("postproduction", {})
        if post.get("enabled"):
            from .postprocess import compose_project

            final_output = output_dir / post.get("final_output", "final.mp4")
            compose_project(project, state, output_dir, final_output, post)
            print(f"Final video: {final_output}")
        return output_dir
    finally:
        if backend_process is not None and config.get("stop_backend_on_exit", False):
            backend_process.terminate()
        if backend_log is not None:
            backend_log.close()
