"""Small PyAV media helpers used as fallbacks when ffmpeg is not on PATH."""

from __future__ import annotations

from pathlib import Path

import av


def extract_last_frame(source: Path, destination: Path) -> None:
    """Write the final video frame of ``source`` to ``destination`` as PNG."""
    container = av.open(str(source))
    stream = next(item for item in container.streams if item.type == "video")
    last = None
    for frame in container.decode(stream):
        last = frame
    if last is None:
        raise RuntimeError(f"No video frames found: {source}")
    last.to_image().save(str(destination), format="PNG")
    container.close()


def concat_videos(files: list[Path], destination: Path) -> None:
    """Concatenate videos that share codec and dimensions using PyAV."""
    first = av.open(str(files[0]))
    video_in = next(item for item in first.streams if item.type == "video")
    fps = float(video_in.average_rate or 24)
    width, height = video_in.codec_context.width, video_in.codec_context.height
    output = av.open(str(destination), "w")
    video_out = output.add_stream("libx264", rate=fps)
    video_out.width, video_out.height = width, height
    video_out.pix_fmt = "yuv420p"
    for source in files:
        container = av.open(str(source))
        stream = next(item for item in container.streams if item.type == "video")
        for frame in container.decode(stream):
            frame = frame.reformat(width=width, height=height, format="yuv420p")
            for packet in video_out.encode(frame):
                output.mux(packet)
        container.close()
    for packet in video_out.encode():
        output.mux(packet)
    output.close()
    first.close()
