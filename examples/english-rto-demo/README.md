# English Demo

This is a deliberately small, fresh demo manifest for the article project. It is not copied from another video project and contains no employer-specific material.

The demo is an English explainer about return-to-office policies. Its purpose is to make the infrastructure experiment concrete: a viewer can see the output, while the repository explains how the output was produced and what "zero-cost" does and does not mean.

## Two-phase workflow

The demo exercises the full pipeline:

1. **Generation** — `local-ai-video run --manifest project.json --config <local>` queues the three shots on the local ComfyUI backend, downloads the clips into `outputs/english-rto-demo/`, and records `state.json`. The `first_frame_from_previous` flags chain each shot's last frame into the next.
2. **Postproduction** — the same command with `--post-only` synthesizes the English narration (the demo pins the offline SAPI provider; switch `provider` to `edge` and pick a neural voice for better quality), renders the deterministic title bars, cards, and subtitles, and composes `outputs/english-rto-demo/english-rto-demo.mp4`.

Both phases are fully scripted; no browser interaction is required.

## GPU-free checks

```powershell
local-ai-video validate --manifest project.json
local-ai-video plan --manifest project.json
local-ai-video check --manifest project.json
```

The repository only ships the manifest. The exact local workflow, model weights, and licenses must be documented before a machine-specific run is attempted.
