from pathlib import Path
from .process import ffmpeg_input, stream_process, ToolError


def export_snippets(audio, output: Path, config, file_index: int):
    if not audio.defects:
        return
    folder = output / "defect_snippets"
    folder.mkdir(exist_ok=True)
    for n, event in enumerate(audio.defects, 1):
        relative = Path("defect_snippets") / f"file_{file_index:05d}_event_{n:05d}.wav"
        target = output / relative
        # Exclusive target check plus -n: existing files can never be overwritten.
        if target.exists():
            audio.operational("snippet_export", f"Snippet already exists: {relative}", required=True)
            continue
        if getattr(event, "channel_events", None):
            first = event.cluster_first_sample / audio.sample_rate
            last = (event.cluster_last_sample + 1) / audio.sample_rate
        else:
            first = event.timestamp_seconds
            last = event.timestamp_seconds + event.duration_seconds
        start = max(0, first-config["defects"]["snippet_before_seconds"])
        end = last+config["defects"]["snippet_after_seconds"]
        if audio.decoded_duration_seconds:
            end = min(end, audio.decoded_duration_seconds)
        args = ffmpeg_input(audio.path)
        index = args.index("-i")
        args[index:index] = ["-ss", f"{start:.12f}"]
        args += ["-n", "-t", f"{end-start:.12f}", "-map_metadata", "-1", "-c:a", "pcm_f32le", "-rf64", "auto", str(target)]
        try:
            with stream_process(args, config["process_timeout_seconds"]) as pipe:
                while pipe.read(8192):
                    pass
            event.snippet = relative.as_posix()
        except (ToolError, OSError) as exc:
            audio.operational("snippet_export", f"Evidence export failed for event {n}: {exc}", required=True)
