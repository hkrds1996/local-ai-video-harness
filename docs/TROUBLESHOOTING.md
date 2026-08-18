# Troubleshooting

## The manifest is rejected

Run `validate` and address every reported field. Shot identifiers must be unique and durations must be positive numbers.

## The server is not ready

Confirm that ComfyUI is running and that `server_url` points to its API listener. Test the `/system_stats` endpoint from the same machine. Check firewall rules and port conflicts.

## A workflow node is not found

The configured identifier must match a top-level key in the API-format workflow. Browser canvas exports use a different structure and are not accepted by the current generic runner.

## A workflow input is not found

Inspect the selected node's `inputs` object. Different custom nodes may call the prompt or seed input by a different name.

## The job times out

Increase `timeout_seconds` only after confirming the server is still processing. A timeout does not cancel a server-side job. Check ComfyUI history and logs before submitting a duplicate.

## The server completes but no file is downloaded

Inspect the history object. The current collector recognizes `videos`, `gifs`, `images`, and `audio`. A custom output type requires an adapter.

## Resume skips the wrong output

The current state file checks only whether previously recorded files still exist. It does not compare prompt or workflow hashes. Use a separate output directory after changing the manifest, workflow, or model.

## Generated text is unreadable

Do not ask the video model to render exact titles, citations, or subtitles. Generate text-free visual material and render language, numbers, and charts deterministically during post-production.

## Output continuity is weak

Continuity chaining is supported when the workflow exposes a `first_frame` input. Each shot that declares `first_frame_from_previous` receives the last frame of the previous accepted output as a conditioning image; prompts should also repeat shared subject, scene, and style anchors. Run `local-ai-video check --manifest <project>` for a static report on anchors, durations, and chaining flags. Note that chaining cannot fix prompt drift when the model itself is inconsistent.

## Narration fails over the network

The `edge` provider requires outbound access to Microsoft's speech service. If the machine is offline, switch the manifest to `"provider": "sapi"` with a locally installed Windows voice, or regenerate with `--post-only --force-tts` after changing the provider.

## The final video has no audio

Postproduction discards model-generated audio by design; the final track comes from the narration synthesis step. Confirm that `narration.segments` is present and that the TTS step printed one entry per segment. `_narration.m4a` in the output directory is the assembled track.
