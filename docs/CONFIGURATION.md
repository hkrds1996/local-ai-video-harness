# Configuration Reference

The repository separates public project intent from private machine configuration.

## Public project manifest

The manifest can be committed. Required top-level keys are:

| Key | Type | Purpose |
|---|---|---|
| `name` | string | Stable machine-friendly project identifier |
| `title` | string | Human-readable project title |
| `render` | object | Intended width, height, and frame rate |
| `shots` | array | Ordered generation units |

Each shot requires:

| Key | Type | Purpose |
|---|---|---|
| `id` | string | Unique state and output identifier |
| `prompt` | string | Model-facing visual instruction |
| `duration_seconds` | number | Planned duration used for validation and reporting |

The generic API path does not inject `duration_seconds`. The included MiniMax H3 adapter maps it into that model's graph.

## Private local configuration

`config.local.json` should not be committed. Supported keys are:

| Key | Required | Default | Purpose |
|---|---|---|---|
| `server_url` | yes | none | Base URL of the local ComfyUI API |
| `workflow_api` | yes | none | Absolute or working-directory-relative path to an API-format workflow |
| `output_dir` | no | `outputs` | State and media destination |
| `workflow_format` | no | `auto` | `api`, `canvas`, or automatic format detection |
| `prompt_node` | API workflows | none | Node identifier containing the prompt input |
| `prompt_input` | no | `text` | Prompt input name |
| `seed_node` | API workflows | none | Node identifier containing the seed input |
| `seed_input` | no | `seed` | Seed input name |
| `timeout_seconds` | no | `3600` | Maximum wait per submitted prompt |
| `poll_seconds` | no | `2` | History polling interval |
| `startup_timeout_seconds` | no | `240` | Seconds to wait after launching the backend |
| `start_command` | no | none | JSON array containing the backend executable and arguments |
| `start_cwd` | no | current directory | Working directory for the backend process |
| `stop_backend_on_exit` | no | `false` | Terminate a backend started by the harness after the run |
| `postproduction` | no | disabled | Narration, captions, font, and final-output settings |

The current postproduction provider is Windows SAPI. Keep machine-specific voice names, paths, and launcher commands in `config.local.json`.

## Finding node identifiers

Inspect the API-format JSON and locate nodes by their `class_type` and `inputs`. Confirm that the configured input exists before running a costly job. The harness fails immediately when a configured node or input is missing.

## Secret handling

Do not place tokens, passwords, signed URLs, employer paths, or private network details in committed manifests. If a future backend requires secrets, load them from environment variables or an ignored secret file and document only the variable names.
