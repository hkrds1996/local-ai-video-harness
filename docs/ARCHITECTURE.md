# Architecture

## Design goal

The project turns an interactive local model workflow into a repeatable job. It treats the model server as one component in a larger production system rather than treating the visual workflow as the entire system.

## Control flow

### Generation

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
state.json + output files + metrics.json
    |
    v
optional: concatenated shots.mp4
```

### Postproduction

```text
project.json narration segments
    |
    v
narration provider (edge or sapi)
    |
    v
per-segment audio + SRT + timeline.json
    |
    v
editorial composer
    +----> clip looped to narration duration
    +----> title bar / source badge / timed cards / subtitles
    +----> audio mux
    |
    v
final H.264/AAC MP4
```

## Components

### Manifest layer

`manifest.py` loads and validates the public project description. The manifest describes intent: title, rendering target, shot identifiers, prompts, durations, and narration segments with their clip and card layout. It deliberately contains no local model paths. Two shapes are accepted: generation-only (`shots`) and editorial (`narration.segments`), which compose.

### CLI layer

`cli.py` exposes four commands:

- `validate` performs static checks without contacting a server;
- `plan` summarizes the execution plan and planned duration;
- `check` runs static shot-continuity checks and writes a JSON report;
- `run` validates inputs and delegates to the runner, with `--dry-run`, `--resume`, `--post-only`, and `--force-tts` flags.

### Execution layer

`runner.py` combines a project manifest with an untracked local configuration. It can clone a generic API-format workflow or invoke the included MiniMax H3 canvas adapter, inject shot-specific values, chain the previous shot's last frame when requested, start the configured backend when necessary, and record successful outputs with timing metrics. It also orchestrates postproduction.

### Narration layer

`narration.py` synthesizes one audio track and one SRT file per narration segment, then writes a `timeline.json` consumed by the composer. The `edge` provider streams word boundaries from Microsoft Edge neural voices (requires network); the `sapi` provider is fully offline and derives subtitles from proportional timing. Existing files are reused across runs unless `--force-tts` is passed.

### Editorial layer

`editorial.py` builds the final MP4 from existing clips: each clip is looped to its narration duration, resized to the render target, and overlaid with a deterministic editorial layer — chapter title, source badge, timed data cards, and subtitles. The overlay layout is authored against a 768x1344 reference and scaled proportionally for other resolutions (16:9 included). Model-generated audio, if any, is discarded in favor of the synthesized track.

### Continuity layer

`continuity.py` statically validates chained H3-style shots: duration limits, prompt-anchor overlap between consecutive shots, and first-frame inheritance flags. It writes a JSON report that can gate a run before expensive generation starts.

### Backend layer

`comfy_api.py` contains the HTTP boundary. It checks server readiness, submits prompts, polls history, detects server-side errors, enumerates media outputs, downloads files, and uploads images for first-frame chaining.

### Media layer

`media.py` provides PyAV fallbacks for last-frame extraction and clip concatenation when `ffmpeg` is not on PATH.

### State layer

The output directory contains `state.json` (one record per completed shot: prompt identifier, downloaded paths, seed, prompt) and `metrics.json` (per-shot generation wall-clock time and run totals, preserved across resumed runs). Both files enable basic resume behavior after process interruption or machine restart.

## Why the layers are separated

- Public manifests remain portable across machines.
- Private model paths remain outside Git.
- Backend-specific API logic can evolve without changing demo content.
- Validation and postproduction can run in CI without a GPU.
- Experiment metadata can refer to a stable manifest and commit.

## Trust boundaries

The harness trusts neither generated media nor remote metadata as publishable output. A complete production pipeline should add duration checks, codec checks, file-size thresholds, visual continuity checks, caption validation, and final composition checks before declaring success. The `check` command covers part of this statically; automated quality scoring remains on the roadmap.
