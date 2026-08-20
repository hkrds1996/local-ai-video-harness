"""Independent narration synthesis and subtitle generation.

Three providers are supported:

- ``edge`` (default): Microsoft Edge neural voices through ``edge-tts``, which
  streams word boundaries that become accurate SRT subtitles. Requires network
  access.
- ``sapi``: the Windows Speech API, fully offline. Subtitles are derived from
  proportional timing over the narrated text.
- ``cosyvoice``: a local CosyVoice 2 instance (Alibaba FunAudioLLM) in
  ``--instruct`` mode. Each segment may carry an ``emotion`` prompt such as
  "用低沉悲伤的语气说", so delivery follows the scene instead of a flat read.
  Fully offline after install. Machine paths (venv python, model dir, reference
  audio) come from the local config's ``cosyvoice`` block.

Every segment produces an audio file and an SRT file inside ``output_dir``,
plus a ``timeline.json`` that records each segment's media paths in order.
The timeline is consumed by :mod:`editorial` during composition.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def stamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def rough_srt(text: str, duration: float) -> str:
    """Proportional SRT for providers without word boundaries."""
    chunks = [part.strip() for part in re.split(r"(?<=[。！？；])", text) if part.strip()]
    if not chunks:
        chunks = [text]
    total = sum(max(1, len(part)) for part in chunks)
    cursor = 0.0
    blocks = []
    for index, part in enumerate(chunks, 1):
        share = duration * max(1, len(part)) / total
        end = duration if index == len(chunks) else cursor + share
        blocks.append(f"{index}\n{stamp(cursor)} --> {stamp(end)}\n{part}\n")
        cursor = end
    return "\n".join(blocks)


async def _edge_segment(text: str, media: Path, subtitles: Path, voice: str, rate: str, pitch: str):
    import edge_tts

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    maker = edge_tts.SubMaker()
    with media.open("wb") as audio:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
            elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
                maker.feed(chunk)
    subtitles.write_text(maker.get_srt(), encoding="utf-8")


def _sapi_segment(text: str, media: Path, subtitles: Path, voice: str, rate: int):
    escaped_text = text.replace("'", "''")
    escaped_media = str(media).replace("'", "''")
    escaped_voice = voice.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{escaped_voice}');$s.Rate={rate};"
        f"$s.SetOutputToWaveFile('{escaped_media}');"
        f"$s.Speak('{escaped_text}');$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    import wave

    with wave.open(str(media), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    subtitles.write_text(rough_srt(text, duration), encoding="utf-8")


def _instruct_for(emotion: str) -> str:
    """Normalize a shorthand emotion into a CosyVoice instruct prompt."""
    emotion = (emotion or "").strip()
    if not emotion:
        return "用平静的语气说"
    if emotion.endswith("说"):
        return emotion
    return f"用{emotion}的语气说"


def _run_cosyvoice_batch(segments: list, output_dir: Path, settings: dict) -> dict:
    """Synthesize all segments in one model load; return {stem: wav_path}."""
    batch_dir = output_dir / "_cosy_batch"
    batch_dir.mkdir(parents=True, exist_ok=True)
    jobs = [{"stem": f"{index:02d}_{segment.get('id', f'segment-{index:02d}')}",
             "text": segment["text"],
             "instruct": _instruct_for(segment.get("emotion", ""))}
            for index, segment in enumerate(segments, 1)]
    job_path = batch_dir / "segments.json"
    job_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run([
        settings["python"], settings["batch_script"],
        settings["model_dir"], settings["prompt_wav"],
        str(job_path), str(batch_dir),
    ], check=True)
    outputs = {}
    for job in jobs:
        wav = batch_dir / f"{job['stem']}.wav"
        if not wav.exists():
            raise RuntimeError(f"CosyVoice produced no audio for {job['stem']}")
        outputs[job["stem"]] = wav
    return outputs


def generate_timeline(project: dict, output_dir: Path, provider: str = "edge", voice: str = None,
                      rate: str = None, pitch: str = "+0Hz", force: bool = False,
                      cosyvoice: dict = None) -> Path:
    """Synthesize one audio + subtitle pair per narration segment.

    Writes ``timeline.json`` into ``output_dir`` and returns its path.
    Existing files are reused unless ``force`` is set. The ``cosyvoice``
    settings dict comes from the local configuration.
    """
    narration = project.get("narration", {})
    segments = narration.get("segments", [])
    if not segments:
        raise ValueError("narration.segments is empty")
    if provider not in {"edge", "sapi", "cosyvoice"}:
        raise ValueError(f"unknown narration provider: {provider}")
    voice = voice or narration.get("voice") or (
        "zh-CN-YunxiNeural" if provider == "edge" else "Microsoft Huihui Desktop"
    )
    rate = rate or narration.get("rate") or ("-4%" if provider == "edge" else "0")
    output_dir.mkdir(parents=True, exist_ok=True)

    cosy_outputs = {}
    if provider == "cosyvoice":
        if not cosyvoice:
            raise ValueError("cosyvoice provider requires a 'cosyvoice' block in the local config")
        cosy_outputs = _run_cosyvoice_batch(segments, output_dir, cosyvoice)

    timeline = []
    for index, segment in enumerate(segments, 1):
        stem = f"{index:02d}_{segment.get('id', f'segment-{index:02d}')}"
        suffix = ".mp3" if provider == "edge" else ".wav"
        media = output_dir / f"{stem}{suffix}"
        subtitles = output_dir / f"{stem}.srt"
        # Dialogue-style projects can assign one voice per segment, e.g. a
        # different character voice for every speaker, plus per-segment rate
        # and pitch for emotional contrast between scenes.
        segment_voice = segment.get("voice") or voice
        segment_rate = segment.get("rate") or rate
        segment_pitch = segment.get("pitch") or pitch
        if force or not media.exists() or not subtitles.exists():
            print(f"[{index}/{len(segments)}] TTS {segment.get('title', stem)}")
            if provider == "edge":
                asyncio.run(_edge_segment(segment["text"], media, subtitles, segment_voice, segment_rate, segment_pitch))
            elif provider == "cosyvoice":
                import shutil
                import wave
                shutil.copy2(cosy_outputs[stem], media)
                with wave.open(str(media), "rb") as wav:
                    duration = wav.getnframes() / wav.getframerate()
                subtitles.write_text(rough_srt(segment["text"], duration), encoding="utf-8")
            else:
                _sapi_segment(segment["text"], media, subtitles, segment_voice, int(segment_rate))
        timeline.append({
            "id": segment.get("id", stem),
            "audio": str(media.resolve()),
            "subtitles": str(subtitles.resolve()),
            "voice": segment_voice,
        })

    timeline_path = output_dir / "timeline.json"
    timeline_path.write_text(
        json.dumps({"provider": provider, "voice": voice, "segments": timeline},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return timeline_path


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate narration clips and subtitles without UI clicks")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--provider", choices=["edge", "sapi"], default="edge")
    parser.add_argument("--voice")
    parser.add_argument("--rate")
    parser.add_argument("--pitch", default="+0Hz")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    project = load_json(args.manifest)
    timeline = generate_timeline(
        project, args.output_dir,
        provider=args.provider, voice=args.voice, rate=args.rate, pitch=args.pitch, force=args.force,
    )
    print(f"Narration ready: {timeline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
