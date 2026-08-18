# Configuration Reference

The repository separates public project intent from private machine configuration.

## Public project manifest

The manifest can be committed. Required top-level keys are `title`, `render`, and at least one of `shots` or `narration.segments`. `name` (legacy) or `slug` identifies the project.

| Key | Type | Purpose |
|---|---|---|
| `title` | string | Human-readable project title |
| `name` / `slug` | string | Stable machine-friendly project identifier |
| `render` | object | Width, height, fps, font, output directory, and final filename |
| `shots` | array | Ordered generation units (may be empty for post-only) |
| `narration` | object | TTS provider settings and narration segments |
| `style_anchor` | string | Shared visual anchor repeated in shot prompts (continuity aid) |
| `default_duration` | number | Fallback shot duration when a shot omits it |

### render

| Key | Required | Purpose |
|---|---|---|
| `width` | yes | Output width in pixels |
| `height` | yes | Output height in pixels |
| `fps` | yes | Output frame rate |
| `font` | no | Path to a TrueType/OpenType font for overlays (defaults to `msyh.ttc`) |
| `output_dir` | no | Directory for narration, overlays, and the final video (defaults to `generated` under the manifest directory) |
| `final_output` | no | Filename of the composed editorial video |

The overlay layout scales proportionally from its 768x1344 reference, so both vertical (9:16) and landscape (16:9) renders stay balanced.

### shots

Each shot requires `id` and `prompt`. Optional keys:

| Key | Purpose |
|---|---|
| `duration` / `duration_seconds` | Planned duration used for validation, planning, and the H3 adapter's frame count |
| `seed` | Fixed seed for reproducible generation; randomized when absent |
| `first_frame_from_previous` | Chain the previous shot's last frame as this shot's `first_frame` |

### narration

| Key | Default | Purpose |
|---|---|---|
| `provider` | `edge` | `edge` (Microsoft Edge neural voices, network required) or `sapi` (offline Windows speech) |
| `voice` | `zh-CN-YunxiNeural` (edge) / `Microsoft Huihui Desktop` (sapi) | Voice name |
| `rate` | `-4%` (edge) / `0` (sapi) | Speaking rate |
| `pitch` | `+0Hz` | Pitch adjustment (edge only) |
| `segments` | — | Ordered narration segments |

Each segment requires `id` and `text`, and references existing media through `clip` (a path relative to the manifest, or absolute). Optional keys:

| Key | Purpose |
|---|---|
| `title` | Chapter title shown in the top overlay bar |
| `source` | Short attribution shown in the source badge |
| `cards` | Timed data-card overlays: `start`, `end`, `headline`, `lines` |

Cards appear while `start <= local_time < end` within the segment.

## Private local configuration

`config.local.json` should not be committed. Supported keys are:

| Key | Required | Default | Purpose |
|---|---|---|---|
| `server_url` | yes | none | Base URL of the local ComfyUI API |
| `workflow_api` | yes | none | Absolute or working-directory-relative path to an API-format or canvas-format workflow |
| `output_dir` | no | `generated` | State, media, and final-output destination |
| `workflow_format` | no | `auto` | `api`, `canvas`, or automatic format detection |
| `prompt_node` | API workflows | none | Node identifier containing the prompt input |
| `prompt_input` | no | `text` | Prompt input name |
| `seed_node` | API workflows | none | Node identifier containing the seed input |
| `seed_input` | no | `seed` | Seed input name |
| `default_duration` | no | `5` | Fallback shot duration in seconds |
| `timeout_seconds` | no | `3600` | Maximum wait per submitted prompt |
| `poll_seconds` | no | `2` | History polling interval |
| `startup_timeout_seconds` | no | `240` | Seconds to wait after launching the backend |
| `comfy_root` | no | none | ComfyUI portable root; `start_script` is resolved inside it |
| `start_script` | no | `start_h3_low_vram.bat` | Backend launcher script under `comfy_root` |
| `start_command` | no | none | Legacy alternative: JSON array of backend executable and arguments |
| `start_cwd` | no | current directory | Legacy working directory for `start_command` |
| `stop_comfy_on_exit` / `stop_backend_on_exit` | no | `false` | Terminate a backend started by the harness after the run |
| `ffmpeg` | no | `ffmpeg` | ffmpeg executable name or path for concat and last-frame extraction |

Keep machine-specific voice names, paths, and launcher commands in `config.local.json`.

## Finding node identifiers

Inspect the API-format JSON and locate nodes by their `class_type` and `inputs`. Confirm that the configured input exists before running a costly job. The harness fails immediately when a configured node or input is missing.

## Secret handling

Do not place tokens, passwords, signed URLs, employer paths, or private network details in committed manifests. If a future backend requires secrets, load them from environment variables or an ignored secret file and document only the variable names.
