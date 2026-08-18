# Local AI Video Harness

A manifest-driven Python harness for reproducible local AI video experiments.

The project explores a narrow engineering question: how much of a video-production workflow can run locally, without per-generation video API charges and without manual browser interaction?

The repository provides an English demonstration manifest, a generic ComfyUI API runner, a MiniMax H3 canvas-workflow adapter, independent narration synthesis, and a deterministic editorial composer. It intentionally separates public project intent from private model paths and machine configuration.

## Project status

This is a working foundation rather than a complete video editor.

Implemented:

- static validation of project manifests (generation and editorial shapes);
- execution-plan summaries that require no GPU;
- loading of both API-format and native canvas-format ComfyUI workflows;
- shot-specific prompt, seed, and duration injection;
- optional first-frame continuity chaining between shots;
- headless queue submission through the local HTTP API;
- history polling and server-error detection;
- download of returned video, image, GIF, and audio outputs;
- persistent state, resume after interruption, and generation timing metrics;
- optional automatic ComfyUI startup and shutdown;
- conversion of the tested MiniMax H3 browser-canvas workflow into API jobs;
- independent narration: Edge neural voices with word-boundary SRT subtitles, or fully offline Windows SAPI;
- deterministic editorial composition: chapter titles, source badges, timed data cards, subtitles, and final audio/video mux;
- proportional overlay layout for both vertical (9:16) and landscape (16:9) renders;
- a `--post-only` mode that composes a finished video from existing clips without any GPU work;
- static shot-continuity checks with a JSON report.

Not yet implemented:

- exponential retry with transient and permanent failure classification;
- automatic GPU, energy, and storage telemetry;
- automated quality scoring;
- generic conversion for arbitrary browser-canvas workflows.

The distinction is deliberate: documentation should describe the code that exists, while the roadmap describes the experiment that will be built next.

## Why a harness instead of a visual workflow?

A visual workflow proves that one generation can work. A harness makes repeated runs inspectable and reproducible.

The harness adds the system-level concerns that an interactive graph does not provide by itself:

- a versionable project manifest;
- separation of public inputs from private machine paths;
- deterministic shot ordering;
- explicit server polling and timeout behavior;
- state persisted after every successful shot;
- resumable execution after interruption;
- output naming independent of backend-generated filenames;
- a place to add validation, cost telemetry, and quality gates.

## Repository layout

```text
local-ai-video-harness/
|-- config.example.json
|-- examples/
|   `-- english-rto-demo/
|       |-- project.json
|       `-- README.md
|-- docs/
|   |-- ARCHITECTURE.md
|   |-- CONFIGURATION.md
|   |-- COST_MODEL.md
|   |-- EXPERIMENT_LOG_TEMPLATE.md
|   |-- REPRODUCE.md
|   `-- TROUBLESHOOTING.md
|-- scripts/
|   `-- validate_demo.ps1
|-- src/local_ai_video_harness/
|   |-- cli.py
|   |-- comfy_api.py
|   |-- continuity.py
|   |-- editorial.py
|   |-- manifest.py
|   |-- media.py
|   |-- minimax_h3_canvas.py
|   |-- narration.py
|   `-- runner.py
|-- LICENSE
|-- pyproject.toml
`-- README.md
```

No model weights, generated media, local workflows, credentials, or machine-specific configuration are committed.

## Execution model

### Generation phase

```text
public project manifest
        +
private local configuration
        +
API-format workflow template or supported H3 canvas workflow
        |
        v
manifest validation
        |
        v
one workflow clone per shot
        |
        v
prompt, seed, duration injection (+ optional first-frame chain)
        |
        v
local ComfyUI HTTP API
        |
        v
downloaded outputs + state.json
```

### Postproduction phase

```text
manifest narration segments (text, clip, cards)
        +
TTS provider (Edge neural voices or Windows SAPI)
        |
        v
per-segment audio + SRT subtitles + timeline.json
        |
        v
clip looped to narration duration
        |
        v
editorial overlay (title bar, source badge, timed cards, subtitles)
        |
        v
final H.264/AAC MP4
```

See [Architecture](docs/ARCHITECTURE.md) for component boundaries and planned extensions.

## Requirements

For validation, planning, and postproduction:

- Python 3.10 or newer;
- PyAV and Pillow (installed by pip);
- the Edge narration provider additionally requires network access and `edge-tts` (optional extra);
- system `ffmpeg` is used when available for last-frame extraction and shot concatenation, with PyAV fallbacks.

For generation:

- a local ComfyUI server, either already running or configured for automatic startup;
- a successfully tested API-format workflow, or the supported MiniMax H3 canvas workflow;
- locally installed model weights and custom nodes required by that workflow;
- enough GPU memory and disk capacity for the chosen model;
- permission to use the model, workflow, voice, fonts, and generated output under their respective licenses.

The harness does not download or redistribute model weights.

## Installation

```powershell
git clone https://github.com/hkrds1996/local-ai-video-harness.git
cd local-ai-video-harness

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install -e ".[narration]"   # optional: Edge neural voices
```

Confirm the command is available:

```powershell
local-ai-video --help
```

The module form is equivalent:

```powershell
python -m local_ai_video_harness.cli --help
```

## Validate, inspect, and check the demo

The included demo is an English return-to-office explainer. The topic gives the experiment a concrete output; it is not the technical focus of the repository.

```powershell
local-ai-video validate --manifest examples/english-rto-demo/project.json
local-ai-video plan --manifest examples/english-rto-demo/project.json
```

Expected plan summary:

```text
Project: Return to Office: A Global Policy Experiment
Shots: 3
Narration segments: 3
Planned generation duration: 18.0s
Render: 768x1344 @ 24fps
  01 office-morning: 6s
  02 hybrid-day: 6s
  03 future-work: 6s
```

Static continuity checks produce a JSON report without contacting a server:

```powershell
local-ai-video check --manifest examples/english-rto-demo/project.json
```

These commands do not connect to ComfyUI and are suitable for CI validation.

## Configure local generation

Copy the example configuration:

```powershell
Copy-Item config.example.json config.local.json
```

Edit the local copy:

```json
{
  "server_url": "http://127.0.0.1:8188",
  "workflow_api": "C:/path/to/ComfyUI_api_or_canvas_workflow.json",
  "output_dir": "generated",
  "workflow_format": "auto",
  "prompt_node": "12",
  "prompt_input": "text",
  "seed_node": "15",
  "seed_input": "seed",
  "default_duration": 5,
  "timeout_seconds": 3600,
  "poll_seconds": 2,
  "startup_timeout_seconds": 240,
  "comfy_root": "C:/path/to/ComfyUI_windows_portable",
  "start_script": "start_h3_low_vram.bat",
  "stop_comfy_on_exit": false,
  "ffmpeg": "ffmpeg"
}
```

`config.local.json` is ignored by Git. Do not commit private paths, tokens, internal hostnames, or credentials.

For generic workflows, use ComfyUI API format and configure `prompt_node`/`seed_node`. The repository also includes a narrow adapter for the tested MiniMax H3 browser-canvas export; set `workflow_format` to `canvas` or let `auto` detect it. It is intentionally model-specific and does not imply compatibility with arbitrary canvas workflows.

See [Configuration Reference](docs/CONFIGURATION.md) for field definitions and node-mapping guidance.

## Run headlessly

### Generate shots

Execute the command below. If the server is unavailable and a start command is configured, the harness starts it and waits for readiness without browser interaction.

```powershell
local-ai-video run `
  --manifest examples/english-rto-demo/project.json `
  --config config.local.json
```

For every shot, the runner:

1. clones or converts the workflow template;
2. injects the shot prompt, seed, and duration;
3. optionally chains the previous shot's last frame as `first_frame`;
4. submits the workflow to `/prompt`;
5. polls `/history/{prompt_id}`;
6. detects a reported server error;
7. downloads returned media through `/view`;
8. writes the shot result to `state.json`;
9. concatenates the clips into `shots.mp4`.

Run the same command with `--resume` after an interruption. Completed shots are skipped when every recorded output file still exists. `--dry-run` prints the execution plan without starting the backend.

### Postproduction only

If the clips already exist (from a previous generation run or from your own footage), the `--post-only` mode skips ComfyUI entirely and builds the finished editorial video:

```powershell
local-ai-video run `
  --manifest examples/english-rto-demo/project.json `
  --config config.local.json `
  --post-only
```

This synthesizes narration for every narration segment, renders the deterministic overlays, and composes the final MP4 named by `render.final_output`. Use `--force-tts` to regenerate cached narration audio and subtitles.

## Manifest design

The public manifest expresses what should be generated, not where a model is installed.

```json
{
  "slug": "example-project",
  "title": "Example Project",
  "render": {
    "width": 768,
    "height": 1344,
    "fps": 24,
    "font": "C:/Windows/Fonts/msyh.ttc",
    "output_dir": "generated",
    "final_output": "example-final.mp4"
  },
  "shots": [
    {
      "id": "opening-shot",
      "duration": 6,
      "prompt": "Documentary B-roll with no readable text or logos",
      "first_frame_from_previous": false
    }
  ],
  "narration": {
    "provider": "edge",
    "voice": "zh-CN-YunxiNeural",
    "rate": "-4%",
    "segments": [
      {
        "id": "opening-shot",
        "title": "Chapter one",
        "source": "Public records",
        "clip": "generated/01_opening-shot_1.mp4",
        "text": "The narration read over this clip.",
        "cards": [
          {"start": 5, "end": 15, "headline": "Key figure", "lines": ["94% decline", "14.75 billion EUR loss"]}
        ]
      }
    ]
  }
}
```

The generic API path uses `duration` (or the legacy `duration_seconds`) for validation, planning, and the MiniMax H3 adapter's frame count. `style_anchor` and per-shot `first_frame_from_previous` support visual continuity between short clips. Narration segments may reference any video file; `clip` paths are resolved relative to the manifest.

A legacy manifest shape is still accepted: top-level `name` instead of `slug`, and `duration_seconds` per shot.

## State and reproducibility

The output directory contains a `state.json` file with one record per successful shot. It stores the backend prompt identifier, downloaded file paths, seed, and prompt. A `metrics.json` file records per-shot generation wall-clock time and total run time, preserved across resumed runs.

Current resume semantics are intentionally simple:

- if the state entry exists and every recorded file exists, skip the shot;
- otherwise submit the shot again.

The state file does not yet hash prompts, workflows, model weights, or environment versions. When any of those inputs change, use a separate output directory or invalidate only the reviewed state entries. See [Reproduction Guide](docs/REPRODUCE.md).

## What "zero-cost AI" means

The experiment uses "zero-cost AI" as a question, not a conclusion.

The narrow target is zero marginal video API charge. Local inference still has costs:

- GPU purchase, depreciation, or rental;
- electricity and cooling;
- storage and backup retention;
- model and environment setup;
- engineering and maintenance time;
- failed generations and retries;
- narration and post-production;
- licensing and compliance review;
- human quality control.

The repository therefore measures cash cost, amortized infrastructure cost, and full production cost separately. See [Cost Model](docs/COST_MODEL.md) and [Experiment Log Template](docs/EXPERIMENT_LOG_TEMPLATE.md).

## Security, privacy, and independence

This is an independent personal project. It is not affiliated with, sponsored by, or endorsed by any employer. It contains no employer code, data, credentials, internal documentation, or confidential information.

Before publishing a local configuration or workflow:

- remove usernames and absolute personal paths;
- remove tokens, signed URLs, and private hostnames;
- confirm that model and workflow licenses allow the intended use;
- avoid committing generated media that contains personal or copyrighted material;
- keep employer systems, equipment, data, and work product outside the project;
- describe online dependencies honestly instead of calling a hybrid run fully local.

## Failure handling

The runner raises an error when:

- the server does not become ready;
- a configured workflow node or input does not exist;
- the backend reports an error in history;
- a submitted prompt exceeds its timeout;
- the backend returns no recognized media output;
- a narration segment references a missing clip during postproduction.

See [Troubleshooting](docs/TROUBLESHOOTING.md) before increasing timeouts or resubmitting expensive jobs.

## Roadmap

The next engineering milestones are:

1. exponential retry with transient and permanent failure classification;
2. GPU, energy, runtime, and storage telemetry;
3. quality reports and cost-per-publishable-output metrics;
4. unit tests and a GPU-free mocked API integration test;
5. configurable caption themes and timeline transitions;
6. additional workflow adapters with explicit compatibility checks.

## Contributing

Issues and pull requests should include:

- the smallest reproducible manifest;
- a sanitized configuration shape;
- the ComfyUI and Python versions;
- whether the workflow is API format or browser canvas format;
- relevant error output with credentials and personal paths removed.

Do not attach model weights, proprietary workflows, confidential logs, or unlicensed generated media.

## License

Original code and documentation are licensed under Apache-2.0. Model weights, custom nodes, workflows, fonts, voices, source material, and generated media remain subject to their own licenses.
