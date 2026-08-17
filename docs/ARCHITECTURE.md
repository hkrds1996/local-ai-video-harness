# Architecture

## Design goal

The project turns an interactive local model workflow into a repeatable job. It treats the model server as one component in a larger production system rather than treating the visual workflow as the entire system.

## Control flow

```text
project.json
    |
    v
manifest validation -----> execution plan
    |
    v
workflow template + local config
    |
    v
API workflow injection or supported H3 canvas conversion
    |
    v
ComfyUI HTTP API
    |
    +----> queue prompt
    +----> poll job history
    +----> collect output descriptors
    +----> download media
    |
    v
state.json + output files
    |
    v
local narration + deterministic captions + final MP4
```

## Components

### Manifest layer

`manifest.py` loads and validates the public project description. The manifest describes intent: title, rendering target, shot identifiers, prompts, and planned durations. It deliberately contains no local model paths.

### CLI layer

`cli.py` exposes three commands:

- `validate` performs static checks without contacting a server;
- `plan` summarizes the execution plan and planned duration;
- `run` validates inputs and delegates execution to the runner.

### Execution layer

`runner.py` combines a project manifest with an untracked local configuration. It can clone a generic API-format workflow or invoke the included MiniMax H3 canvas adapter, inject shot-specific values, start the configured backend when necessary, and record successful outputs.

### Postproduction layer

`postprocess.py` synthesizes narration through Windows SAPI, renders exact English text with installed fonts, loops or trims each visual to the narration duration, discards unreliable model audio, and writes a final H.264/AAC MP4.

### Backend layer

`comfy_api.py` contains the HTTP boundary. It checks server readiness, submits prompts, polls history, detects server-side errors, enumerates media outputs, and downloads files.

### State layer

The output directory contains `state.json`. Each completed shot records the server prompt identifier and downloaded paths. The file enables basic resume behavior after process interruption or machine restart.

## Why the layers are separated

- Public manifests remain portable across machines.
- Private model paths remain outside Git.
- Backend-specific API logic can evolve without changing demo content.
- Validation can run in CI without a GPU.
- Experiment metadata can refer to a stable manifest and commit.

## Trust boundaries

The harness trusts neither generated media nor remote metadata as publishable output. A complete production pipeline should add duration checks, codec checks, file-size thresholds, visual continuity checks, caption validation, and final composition checks before declaring success.

## Current versus planned functionality

Implemented:

- manifest validation;
- execution planning;
- API-format workflow loading;
- prompt and seed injection;
- ComfyUI queue and history polling;
- media download;
- basic state-based resume.
- optional backend startup and shutdown;
- MiniMax H3 canvas-workflow conversion;
- model-specific duration injection for that adapter;
- local SAPI narration and deterministic captions;
- final timeline composition and audio replacement;
- generation timing retained across resume runs.

Planned:

- adapters for additional canvas workflows and models;
- generic duration and resolution mappings;
- exponential retry and failure classification;
- first-frame and last-frame continuity adapters;
- cross-platform narration providers;
- configurable captions and charts;
- energy and GPU telemetry;
- automated quality reports.
