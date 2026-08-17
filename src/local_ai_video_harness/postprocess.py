from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path

import av
from PIL import Image, ImageDraw, ImageFont, ImageOps


VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)


def _wrap_words(text: str, max_chars: int):
    lines = []
    current = []
    length = 0
    for word in text.split():
        added = len(word) + (1 if current else 0)
        if current and length + added > max_chars:
            lines.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length += added
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _synthesize_sapi(text: str, destination: Path, voice: str, rate: int):
    safe_text = text.replace("'", "''")
    safe_path = str(destination).replace("'", "''")
    safe_voice = voice.replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$speaker.SelectVoice('{safe_voice}');"
        f"$speaker.Rate={int(rate)};"
        f"$speaker.SetOutputToWaveFile('{safe_path}');"
        f"$speaker.Speak('{safe_text}');"
        "$speaker.Dispose();"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], check=True)


def _encode_audio(audio_files: list[Path], destination: Path):
    output = av.open(str(destination), "w")
    stream_out = output.add_stream("aac", rate=48000)
    stream_out.layout = "stereo"
    stream_out.bit_rate = 192000
    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
    cursor = 0
    durations = []
    for source in audio_files:
        start = cursor
        container = av.open(str(source))
        stream = next(item for item in container.streams if item.type == "audio")
        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                converted.pts = cursor
                converted.time_base = Fraction(1, 48000)
                cursor += converted.samples
                for packet in stream_out.encode(converted):
                    output.mux(packet)
        container.close()
        durations.append((cursor - start) / 48000)
    for converted in resampler.resample(None):
        converted.pts = cursor
        converted.time_base = Fraction(1, 48000)
        cursor += converted.samples
        for packet in stream_out.encode(converted):
            output.mux(packet)
    for packet in stream_out.encode():
        output.mux(packet)
    output.close()
    return durations


def _overlay(image: Image.Image, caption: str, fonts):
    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    title_font, label_font, caption_font = fonts
    draw.rectangle((0, 0, width, 155), fill=(5, 12, 22, 255))
    draw.text((42, 34), "LOCAL AI VIDEO EXPERIMENT", font=title_font, fill=(255, 255, 255, 255))
    draw.text((44, 100), "LOCAL VIDEO MODEL  |  AUTOMATED HARNESS", font=label_font, fill=(90, 196, 255, 255))
    wrapped = _wrap_words(caption, 31)
    box = draw.multiline_textbbox((0, 0), wrapped, font=caption_font, spacing=12, align="center")
    text_height = box[3] - box[1]
    top = height - text_height - 115
    draw.rounded_rectangle((28, top - 22, width - 28, height - 55), 18, fill=(0, 0, 0, 255))
    draw.multiline_text(
        (width / 2, top),
        wrapped,
        font=caption_font,
        fill=(255, 255, 255, 255),
        spacing=12,
        anchor="ma",
        align="center",
    )
    return image.convert("RGB")


def _is_nearly_black(image: Image.Image):
    grayscale = image.convert("L").resize((32, 32))
    pixels = list(grayscale.getdata())
    return sum(pixels) / len(pixels) < 4


def _render_video(sections: list[dict], durations: list[float], destination: Path, render: dict, font_path: str):
    fps = int(render["fps"])
    width = int(render["width"])
    height = int(render["height"])
    output = av.open(str(destination), "w")
    stream_out = output.add_stream("libx264", rate=fps)
    stream_out.width = width
    stream_out.height = height
    stream_out.pix_fmt = "yuv420p"
    stream_out.options = {"crf": "19", "preset": "medium"}
    fonts = (_font(font_path, 36), _font(font_path, 21), _font(font_path, 42))
    frame_cursor = 0
    for index, (section, duration) in enumerate(zip(sections, durations), 1):
        required = max(1, round(duration * fps))
        produced = 0
        print(f"[{index}/{len(sections)}] compose {section['shot_id']} ({duration:.1f}s)")
        while produced < required:
            container = av.open(str(section["video"]))
            stream = next(item for item in container.streams if item.type == "video")
            decoded = False
            for frame in container.decode(stream):
                if produced >= required:
                    break
                source_image = frame.to_image()
                if not decoded and _is_nearly_black(source_image):
                    continue
                decoded = True
                image = ImageOps.fit(source_image, (width, height), method=Image.Resampling.LANCZOS)
                image = _overlay(image, section["text"], fonts)
                output_frame = av.VideoFrame.from_image(image)
                output_frame.pts = frame_cursor
                output_frame.time_base = Fraction(1, fps)
                frame_cursor += 1
                produced += 1
                for packet in stream_out.encode(output_frame):
                    output.mux(packet)
            container.close()
            if not decoded:
                raise RuntimeError(f"No video frames found: {section['video']}")
    for packet in stream_out.encode():
        output.mux(packet)
    output.close()


def _remux(video: Path, audio: Path, destination: Path):
    video_in = av.open(str(video))
    audio_in = av.open(str(audio))
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


def _video_for_shot(state: dict, shot_id: str):
    files = state["shots"][shot_id]["files"]
    match = next((Path(item) for item in files if Path(item).suffix.lower() in VIDEO_SUFFIXES), None)
    if match is None:
        raise RuntimeError(f"No video output recorded for shot {shot_id}")
    return match


def compose_project(project: dict, state: dict, output_dir: Path, final_output: Path, config: dict):
    provider = config.get("provider", "sapi")
    if provider != "sapi":
        raise ValueError("The current public composer supports the Windows SAPI provider only")
    segments = project.get("narration", {}).get("segments", [])
    if not segments:
        raise ValueError("narration.segments is required for postproduction")
    narration_dir = output_dir / "narration"
    narration_dir.mkdir(parents=True, exist_ok=True)
    voice = config.get("voice", "Microsoft David Desktop")
    rate = int(config.get("rate", 1))
    sections = []
    audio_files = []
    for index, segment in enumerate(segments, 1):
        audio = narration_dir / f"{index:02d}_{segment['shot_id']}.wav"
        _synthesize_sapi(segment["text"], audio, voice, rate)
        audio_files.append(audio)
        sections.append({
            "shot_id": segment["shot_id"],
            "text": segment["text"],
            "video": _video_for_shot(state, segment["shot_id"]),
        })
    audio_temp = output_dir / "_narration.m4a"
    video_temp = output_dir / "_video_with_captions.mp4"
    durations = _encode_audio(audio_files, audio_temp)
    _render_video(sections, durations, video_temp, project["render"], config.get("font", "C:/Windows/Fonts/arial.ttf"))
    _remux(video_temp, audio_temp, final_output)
