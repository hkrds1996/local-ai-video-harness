"""Editorial composition: build the final video from clips, narration, and overlays.

For every narration segment the composer:

1. opens the segment's ``clip`` (any video file; it loops to fill the
   narration duration);
2. resizes each frame to the render target;
3. overlays the deterministic editorial layer — chapter title bar, source
   badge, timed data cards, and subtitles;
4. encodes the result and muxes the narration audio track produced by
   :mod:`narration`.

The overlay layout is authored against a 768x1344 vertical reference and
scaled proportionally for other resolutions (for example 1920x1080). At the
reference size every scale factor is exactly 1.0, so legacy output is
unchanged.
"""
from __future__ import annotations

import json
import math
import re
import shutil
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REFERENCE = (768, 1344)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)


def wrap_cjk(text: str, width: int) -> str:
    """Wrap CJK-aware text so proportional widths stay inside ``width``."""
    text = re.sub(r"\s+", " ", text).strip()
    lines, current, count = [], "", 0.0
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9.%+<>=_–—-]*|\n|.", text)
    for token in tokens:
        if token == "\n":
            if current.strip():
                lines.append(current.strip())
            current, count = "", 0.0
            continue
        weight = sum(0.55 if ord(character) < 128 else 1.0 for character in token)
        if current and count + weight > width:
            lines.append(current.strip())
            current, count = token, weight
        else:
            current += token
            count += weight
    if current.strip():
        lines.append(current.strip())
    return "\n".join(lines)


def editorial_cues(text: str, duration: float):
    """Split narration text into proportional subtitle cues.

    Punctuation and abbreviations are preserved from the authored text.
    Proportional timing is less granular than TTS word boundaries but reads
    naturally and works for every provider.
    """
    parts = [part.strip() for part in re.split(r"(?<=[，。！？；：.!?])", text) if part.strip()]
    expanded = []
    for part in parts:
        if len(part) <= 31:
            expanded.append(part)
        else:
            midpoint = len(part) // 2
            split_at = max(part.rfind("、", 0, midpoint + 5), part.rfind(" ", 0, midpoint + 5))
            if split_at < 8:
                split_at = midpoint
            expanded.extend([part[: split_at + 1].strip(), part[split_at + 1:].strip()])
    total = sum(max(1, len(part)) for part in expanded)
    cursor, cues = 0.0, []
    for index, part in enumerate(expanded):
        end = duration if index == len(expanded) - 1 else cursor + duration * max(1, len(part)) / total
        cues.append((cursor, end, part))
        cursor = end
    return cues


def _layout_scale(width: int, height: int):
    """Return (font_scale, line_scale) for the render target.

    The authored layout targets a 768x1344 vertical reference. On portrait
    canvases fonts scale with width. On landscape canvases vertical space is
    scarce, so font growth is capped while line wrap widens to use the extra
    width; this keeps text from colliding with adjacent elements.
    """
    sx = width / REFERENCE[0]
    sy = height / REFERENCE[1]
    if sy >= sx:
        return sx, 1.0
    font_scale = min(sx, 1.4 * sy)
    return font_scale, sx / font_scale


def overlay_editorial(image: Image.Image, section: dict, local_time: float, cues, fonts):
    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    title_font, source_font, body_font, subtitle_font = fonts
    sx = width / REFERENCE[0]
    sy = height / REFERENCE[1]
    _, line_scale = _layout_scale(width, height)

    # A fixed gradient-like shade keeps generated backgrounds from competing with real text.
    draw.rectangle((0, 0, width, round(190 * sy)), fill=(5, 12, 22, 145))
    draw.rectangle((0, height - round(300 * sy), width, height), fill=(5, 12, 22, 175))
    draw.text((round(46 * sx), round(38 * sy)), section.get("title", ""), font=title_font, fill=(255, 255, 255, 255))
    source = section.get("source", "")
    if source:
        badge_w = min(width - 44 * sx, 44 * sx + len(source) * 24 * sx)
        draw.rounded_rectangle((44 * sx, 128 * sy, badge_w, 177 * sy), 12, fill=(20, 105, 160, 220))
        draw.text((58 * sx, 137 * sy), source, font=source_font, fill=(245, 250, 255, 255))

    for card in section.get("cards", []):
        if float(card.get("start", 0)) <= local_time < float(card.get("end", 0)):
            top = 260 * sy
            headline = wrap_cjk(card.get("headline", ""), round(17 * line_scale))
            head_box = draw.multiline_textbbox((82 * sx, top + 42 * sy), headline, font=title_font, spacing=8)
            body_y = max(top + 160 * sy, head_box[3] + 14)
            lines = "\n".join("• " + wrap_cjk(line, round(21 * line_scale)) for line in card.get("lines", []))
            body_box = draw.multiline_textbbox((82 * sx, body_y), lines, font=body_font, spacing=13)
            # The box grows with its content instead of clipping dense cards.
            bottom = max(top + 330 * sy, body_box[3] + 22)
            draw.rounded_rectangle(
                (48 * sx, top, width - 48 * sx, bottom), 24,
                fill=(7, 18, 32, 224), outline=(75, 176, 222, 235), width=3,
            )
            draw.multiline_text((82 * sx, top + 42 * sy), headline, font=title_font,
                                fill=(255, 204, 94, 255), spacing=8)
            draw.multiline_text((82 * sx, body_y), lines, font=body_font,
                                fill=(238, 244, 250, 255), spacing=13)
            break

    cue_text = next((text for start, end, text in cues if start <= local_time < end), "")
    if cue_text:
        subtitle = wrap_cjk(cue_text, round(15 * line_scale))
        box = draw.multiline_textbbox((0, 0), subtitle, font=subtitle_font, spacing=9, align="center")
        text_height = box[3] - box[1]
        y = height - 92 * sy - text_height
        draw.rounded_rectangle((34 * sx, y - 18 * sy, width - 34 * sx, height - 48 * sy), 18,
                               fill=(0, 0, 0, 184))
        draw.multiline_text((width / 2, y), subtitle, font=subtitle_font,
                            fill=(255, 255, 255, 255), spacing=9, anchor="ma",
                            align="center", stroke_width=2, stroke_fill=(0, 0, 0, 230))
    return image.convert("RGB")


def layout_warnings(section: dict, width: int, height: int, fonts) -> list[str]:
    """Measure overlay text against its box and report collisions.

    Runs during composition so oversized titles, dense cards, or long
    subtitles surface as warnings instead of overlapping content in the
    finished video.
    """
    warnings = []
    sx = width / REFERENCE[0]
    sy = height / REFERENCE[1]
    _, line_scale = _layout_scale(width, height)
    title_font, source_font, body_font, _ = fonts
    probe = ImageDraw.Draw(Image.new("RGB", (width, height)))
    title = section.get("title", "")
    if title:
        bottom = probe.textbbox((46 * sx, 38 * sy), title, font=title_font)[3]
        if bottom > 128 * sy - 4:
            warnings.append(f"title collides with the source badge (reaches y={bottom:.0f})")
    for card in section.get("cards", []):
        top = 260 * sy
        headline = wrap_cjk(card.get("headline", ""), round(17 * line_scale))
        head_box = probe.multiline_textbbox((82 * sx, top + 42 * sy), headline, font=title_font, spacing=8)
        body_y = max(top + 160 * sy, head_box[3] + 14)
        body = "\n".join("• " + wrap_cjk(line, round(21 * line_scale)) for line in card.get("lines", []))
        body_box = probe.multiline_textbbox((82 * sx, body_y), body, font=body_font, spacing=13)
        if body_box[3] > height - 300 * sy:
            warnings.append(f"card {card.get('headline', '')!r}: bullet lines reach y={body_box[3]:.0f}, past the bottom shade")
    return warnings


def _resample_to_ndarray(path: Path):
    """Decode a file's audio stream to a stereo float32 ndarray (channels, samples).

    Returns None when the file has no audio stream (e.g. chart or screenshot
    clips), letting the music-bed mixer fall back to the plain TTS track.
    """
    container = av.open(str(path))
    try:
        stream = next(item for item in container.streams if item.type == "audio")
    except StopIteration:
        container.close()
        return None
    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
    chunks = []
    for frame in container.decode(stream):
        for converted in resampler.resample(frame):
            chunks.append(converted.to_ndarray())
    for converted in resampler.resample(None):
        chunks.append(converted.to_ndarray())
    container.close()
    if not chunks:
        return None
    return np.concatenate(chunks, axis=1)


def _write_pcm(output, stream_out, data: np.ndarray, cursor: int) -> int:
    """Encode a stereo ndarray as AAC frames and return the new sample cursor."""
    for start in range(0, data.shape[1], 1024):
        block = np.ascontiguousarray(data[:, start:start + 1024])
        frame = av.AudioFrame.from_ndarray(block, format="fltp", layout="stereo")
        frame.sample_rate = 48000
        frame.pts = cursor
        frame.time_base = Fraction(1, 48000)
        for packet in stream_out.encode(frame):
            output.mux(packet)
        cursor += block.shape[1]
    return cursor


def _mix_music_bed(tts_path: Path, clip_path: Path, volume: float, destination: Path):
    """Mix a TTS track with the clip's own audio looped underneath as a music bed.

    The video model's speech output is unreliable (garbled dialogue), but its
    ambient audio is usable as a soundtrack. Speech always comes from the TTS
    track; the clip audio is looped, faded, scaled by ``volume``, and summed
    underneath. Falls back to the plain TTS track when the clip has no audio.
    """
    tts = _resample_to_ndarray(tts_path)
    if tts is None:
        shutil.copyfile(tts_path, destination)
        return
    music = _resample_to_ndarray(clip_path)
    if music is None or music.shape[1] < 4800:
        shutil.copyfile(tts_path, destination)
        return
    target = tts.shape[1]
    music_len = music.shape[1]
    repeats = int(np.ceil(target / music_len))
    music = np.tile(music, (1, repeats))[:, :target]
    fade = min(int(48000 * 0.8), music.shape[1] // 2)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        music[:, :fade] *= ramp
        music[:, -fade:] *= ramp[::-1]
    mixed = np.clip(tts + music * float(volume), -1.0, 1.0)
    output = av.open(str(destination), "w")
    stream_out = output.add_stream("aac", rate=48000)
    stream_out.layout = "stereo"
    stream_out.bit_rate = 192000
    _write_pcm(output, stream_out, mixed, 0)
    for packet in stream_out.encode():
        output.mux(packet)
    output.close()


def build_audio(entries, destination: Path, music_volume: float = 0.0):
    """Assemble the final audio track; return per-segment durations.

    ``entries`` is a list of ``(audio_path, clip_path, volume)`` tuples. When
    ``music_volume`` is nonzero and the entry has a clip with audio, the clip
    audio is mixed under the TTS track as a music bed (see
    :func:`_mix_music_bed`).
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = av.open(str(destination), "w")
    stream_out = output.add_stream("aac", rate=48000)
    stream_out.layout = "stereo"
    stream_out.bit_rate = 192000
    cursor = 0
    durations = []
    for index, (audio_path, clip_path, volume) in enumerate(entries):
        start = cursor
        # One resampler per source: mixed tracks are 48k stereo while TTS
        # audio is often 24k mono; sharing a resampler across both throws
        # "Frame does not match AudioResampler setup".
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        if music_volume and volume and clip_path is not None:
            mixed = audio_path.parent / f"_mixed_{index:02d}.m4a"
            _mix_music_bed(Path(audio_path), clip_path, volume, mixed)
            source = mixed
        else:
            source = audio_path
        container = av.open(str(source))
        stream = next(item for item in container.streams if item.type == "audio")
        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                converted.pts = cursor
                converted.time_base = Fraction(1, 48000)
                cursor += converted.samples
                for packet in stream_out.encode(converted):
                    output.mux(packet)
        for converted in resampler.resample(None):
            converted.pts = cursor
            converted.time_base = Fraction(1, 48000)
            cursor += converted.samples
            for packet in stream_out.encode(converted):
                output.mux(packet)
        container.close()
        durations.append((cursor - start) / 48000)
    for packet in stream_out.encode():
        output.mux(packet)
    output.close()
    return durations


def render_video(sections, durations, destination: Path, fps: int, width: int, height: int, font_path: str):
    output = av.open(str(destination), "w")
    stream_out = output.add_stream("libx264", rate=fps)
    stream_out.width, stream_out.height = width, height
    stream_out.pix_fmt = "yuv420p"
    stream_out.options = {"crf": "19", "preset": "medium"}
    font_scale, _ = _layout_scale(width, height)
    sy = height / REFERENCE[1]
    # The title must stay clear of the source badge row: its real glyph height
    # (about 1.3x the font size) cannot exceed the 128sy badge start.
    title_size = round(min(48 * font_scale, (128 * sy - 38 * sy - 8) / 1.3))
    fonts = (
        font(font_path, title_size),
        font(font_path, round(25 * font_scale)),
        font(font_path, round(31 * font_scale)),
        font(font_path, round(39 * font_scale)),
    )
    frame_cursor = 0
    for section_index, (section, duration) in enumerate(zip(sections, durations), 1):
        sources = [Path(item) for item in (section.get("clips") or [section["clip"]])]
        for source in sources:
            if not source.exists():
                raise FileNotFoundError(source)
        for warning in layout_warnings(section, width, height, fonts):
            print(f"  LAYOUT WARNING ({section.get('id', '?')}): {warning}")
        cues = editorial_cues(section["text"], duration)
        required = max(1, round(duration * fps))
        produced = 0
        print(f"[{section_index}/{len(sections)}] render {section.get('title', sources[0].name)} ({duration:.1f}s)")
        # Cross-cutting: cycle through the section's clips every cut_seconds so
        # short generated footage alternates (A-B-A-B) instead of repeating.
        cut_frames = max(1, round(float(section.get("cut_seconds", 8)) * fps))
        cuts = int(math.ceil(required / cut_frames))
        for cut in range(cuts):
            source = sources[cut % len(sources)]
            target = min(required, (cut + 1) * cut_frames)
            while produced < target:
                container = av.open(str(source))
                stream = next(item for item in container.streams if item.type == "video")
                decoded_any = False
                for frame in container.decode(stream):
                    decoded_any = True
                    if produced >= target:
                        break
                    image = frame.to_image().resize((width, height), Image.Resampling.LANCZOS)
                    image = image.filter(ImageFilter.GaussianBlur(radius=1.35))
                    image = overlay_editorial(image, section, produced / fps, cues, fonts)
                    output_frame = av.VideoFrame.from_image(image)
                    output_frame.pts = frame_cursor
                    output_frame.time_base = Fraction(1, fps)
                    frame_cursor += 1
                    produced += 1
                    for packet in stream_out.encode(output_frame):
                        output.mux(packet)
                container.close()
                if not decoded_any:
                    raise RuntimeError(f"No frames found in {source}")
    for packet in stream_out.encode():
        output.mux(packet)
    output.close()


def remux(video: Path, audio: Path, destination: Path):
    video_in, audio_in = av.open(str(video)), av.open(str(audio))
    video_stream = next(item for item in video_in.streams if item.type == "video")
    audio_stream = next(item for item in audio_in.streams if item.type == "audio")
    output = av.open(str(destination), "w")
    video_out = output.add_stream_from_template(video_stream)
    audio_out = output.add_stream_from_template(audio_stream)
    for packet in video_in.demux(video_stream):
        if packet.dts is not None:
            packet.stream = video_out
            output.mux(packet)
    for packet in audio_in.demux(audio_stream):
        if packet.dts is not None:
            packet.stream = audio_out
            output.mux(packet)
    output.close()
    video_in.close()
    audio_in.close()


def compose(manifest_path: Path, timeline_path: Path, destination: Path):
    manifest, timeline = load_json(manifest_path), load_json(timeline_path)
    narration_segments = manifest["narration"]["segments"]
    timeline_segments = timeline["segments"]
    if len(narration_segments) != len(timeline_segments):
        raise ValueError("narration and TTS timeline segment counts do not match")
    base = manifest_path.parent.resolve()
    sections = []
    for segment, generated in zip(narration_segments, timeline_segments):
        section = dict(segment)
        clip = Path(section["clip"])
        section["clip"] = str((base / clip).resolve()) if not clip.is_absolute() else str(clip)
        if section.get("clips"):
            resolved = []
            for item in section["clips"]:
                path = Path(item)
                resolved.append(str((base / path).resolve()) if not path.is_absolute() else str(path))
            section["clips"] = resolved
        section["subtitles"] = generated["subtitles"]
        sections.append(section)
    output_dir = destination.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_temp = output_dir / "_narration.m4a"
    video_temp = output_dir / "_video_with_titles.mp4"
    narration = manifest.get("narration", {})
    music_volume = float(narration.get("music_volume", 0.0) or 0.0)
    entries = []
    for segment, generated in zip(narration_segments, timeline_segments):
        clip = Path(segment["clip"])
        clip_path = (base / clip).resolve() if not clip.is_absolute() else clip
        volume = float(segment.get("music_volume", music_volume))
        entries.append((Path(generated["audio"]), clip_path if clip_path.exists() else None, volume))
    durations = build_audio(entries, audio_temp, music_volume)
    render = manifest.get("render", {})
    render_video(
        sections,
        durations,
        video_temp,
        int(render.get("fps", 24)),
        int(render.get("width", REFERENCE[0])),
        int(render.get("height", REFERENCE[1])),
        render.get("font", "C:/Windows/Fonts/msyh.ttc"),
    )
    remux(video_temp, audio_temp, destination)
    print(f"Final editorial video: {destination}")
