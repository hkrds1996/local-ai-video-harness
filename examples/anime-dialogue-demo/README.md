# Anime Dialogue Demo

An 8-minute anime short that showcases the dialogue-driven side of the harness, deliberately different from the narration-driven English demo.

The story is original dialogue inspired by the background of the film *Five Centimeters per Second*: two children separated by distance, letters, a snowy night train, and a promise under a cherry tree. All dialogue is original — no film script, footage, or characters are reproduced — and every visual is generated locally by the H3 model from the shot prompts.

## What this demo shows

- **Dialogue instead of narration.** Every narration segment is a spoken exchange with speaker labels, and the subtitles are split on English sentence punctuation.
- **One voice per character.** The manifest assigns `voice` per narration segment (`en-US-JennyNeural` for Haru, `en-US-ChristopherNeural` for Riku), so the same pipeline that reads one narration voice can also act as a two-character dialogue recorder.
- **Emotional delivery.** Each segment overrides `rate` and `pitch` — slow, low scenes for grief and quietness; brighter pacing for the childhood and rocket scenes — so the same neural voice shifts mood between scenes.
- **A music bed from the model's own audio.** The video model's speech output is garbled and unusable, but its ambient audio is a usable soundtrack. The composer now mixes each clip's audio, looped and faded, underneath the TTS track (`narration.music_volume`, 0.15 here) instead of discarding model audio entirely.
- **First-frame continuity chaining.** Shots 2-9 set `first_frame_from_previous`, so each generated clip starts from the last frame of the previous one, keeping the anime scenes visually coherent.
- **Scene cards.** Timed cards place each dialogue in context (time, place, season) without a narrator explaining it.
- **Landscape render.** The layout system scales the same overlay design from its 9:16 reference to 1920x1080.

## Two-phase workflow

1. **Generate the nine clips** (requires the local ComfyUI backend with the H3 workflow):

   ```powershell
   local-ai-video run --manifest project.json --config ..\..\config.local.json
   ```

2. **Compose the final video** (no GPU needed):

   ```powershell
   local-ai-video run --manifest project.json --config ..\..\config.local.json --post-only
   ```

Both phases are fully scripted; no browser interaction is required. Output lands in `generated/anime-dialogue-demo.mp4`.

## GPU-free checks

```powershell
local-ai-video validate --manifest project.json
local-ai-video plan --manifest project.json
local-ai-video check --manifest project.json
```

## Content note

The dialogue, characters (Riku and Haru), and visuals are original. The video is labeled "Inspired by 5cm per Second" in its source badges; it contains no copyrighted film material.
