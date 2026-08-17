# Reproduction Guide

This guide covers the implemented path: validate a manifest, inspect the execution plan, start or connect to local ComfyUI, submit a supported workflow, resume completed shots, and optionally compose narration and captions. It does not install model weights or modify a ComfyUI installation.

## 1. Prerequisites

- Windows, Linux, or macOS with Python 3.10 or newer.
- A local ComfyUI installation if generation will be executed.
- A model and workflow that can run successfully in that installation.
- An API-format workflow, or a MiniMax H3 canvas export compatible with the included adapter.
- Sufficient GPU memory, disk space, and permission to use the selected model.

## 2. Prepare the Python environment

Use Python 3.10 or newer. Install the repository in editable mode:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Verify the CLI:

```powershell
local-ai-video --help
```

## 3. Validate the independent demo

```powershell
python -m local_ai_video_harness.cli validate --manifest examples/english-rto-demo/project.json
python -m local_ai_video_harness.cli plan --manifest examples/english-rto-demo/project.json
```

Validation checks required project fields, render settings, shot identifiers, prompts, and positive durations. Planning prints the total target duration without contacting a model server.

## 4. Prepare a workflow

For a generic workflow, export it in API format and identify:

- the node that receives the positive prompt;
- the name of its text input;
- the node that receives the random seed;
- the name of its seed input.

The generic runner modifies prompt and seed inputs. The included MiniMax H3 adapter additionally converts the tested canvas export and maps prompt, seed, duration, and output prefix. Other canvas exports require their own adapters.

## 5. Create a local configuration

Copy the example without committing the new file:

```powershell
Copy-Item config.example.json config.local.json
```

Edit `config.local.json` with the local server URL, workflow path, and node mappings. The local file is ignored by Git because it may contain machine-specific paths.

## 6. Configure or start the local backend

Either start ComfyUI before the run, or configure `start_command`, `start_cwd`, and `startup_timeout_seconds`. If the API is unavailable, the harness launches that command and waits for readiness. No browser interaction is required.

## 7. Execute the demo

```powershell
python -m local_ai_video_harness.cli run `
  --manifest examples/english-rto-demo/project.json `
  --config config.local.json
```

For every shot, the runner prepares the workflow, submits the job, waits for history, downloads returned media, updates `state.json`, and records generation timing. If postproduction is enabled, it also generates local narration, deterministic captions, and the final MP4.

## 8. Resume an interrupted run

Run the same command again. A shot is skipped when its state entry lists output files and every file still exists. If an output is missing, the shot is submitted again.

The current state mechanism is intentionally conservative. It does not yet hash prompts, workflows, or model versions. If inputs change, use a new output directory or remove only the affected state entry after reviewing it.

## 9. Record the experiment

Copy `docs/EXPERIMENT_LOG_TEMPLATE.md`, record the run, and publish only sanitized aggregate measurements. Keep API charges, electricity, hardware, engineering time, and human review as separate categories.

## 10. Expected limitations

- Arbitrary browser-canvas workflows are not supported; the current converter is specific to the tested MiniMax H3 graph.
- Automatic startup requires a valid local command, and graceful shutdown depends on the configured launcher behavior.
- Generic API workflows do not receive model-specific duration or resolution injection.
- It does not yet chain the final frame of one shot into the next.
- Windows SAPI is the only built-in narration provider.
- It provides resume behavior but not automatic retry backoff.

These limitations are documented so the repository does not claim capabilities it has not implemented.

## 11. Backend extension contract

The repository deliberately does not hard-code a private model path or a specific ComfyUI installation. Add a backend adapter that accepts:

- a local API base URL;
- an API-format workflow;
- prompt and seed input mappings;
- output download rules;
- a local audio/narration provider;
- a state directory.

Keep model-specific paths in an untracked local configuration file. Never commit model weights, tokens, or machine-specific paths.
