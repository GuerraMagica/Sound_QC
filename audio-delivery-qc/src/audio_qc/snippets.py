from pathlib import Path
from .hashing import source_identity_error
from .process import ffmpeg_input, stream_process, ToolError


def _verify_source(audio):
    error = source_identity_error(audio.path, audio.metadata.get("source_signature"))
    if any(d.code in ("source_changed", "snippet_source_changed") for d in audio.operational_diagnostics):
        error = error or "Source identity previously failed verification; rescan a stable copy"
    if error is None:
        return True
    # Revoke all evidence for this source, including earlier completed exports.
    # Keep files for diagnosis, but never advertise them as trusted evidence.
    for event in audio.defects:
        event.snippet = None
        for constituent in getattr(event, "channel_events", ()):
            constituent.snippet = None
    if not any(d.code == "snippet_source_changed" for d in audio.operational_diagnostics):
        audio.operational("snippet_source_changed", f"Evidence blocked: {error}", required=True)
    return False


def export_snippets(audio, output: Path, config, file_index: int, *, cancel=None):
    if not audio.defects or not _verify_source(audio):
        return
    folder = output / "defect_snippets"
    folder.mkdir(exist_ok=True)
    for n, event in enumerate(audio.defects, 1):
        if not _verify_source(audio):
            break
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
            with stream_process(args, config["process_timeout_seconds"], **({"cancel": cancel} if cancel else {})) as pipe:
                while pipe.read(8192):
                    pass
        except (ToolError, OSError) as exc:
            audio.operational("snippet_export", f"Evidence export failed for event {n}: {exc}", required=True)
        else:
            event.snippet = relative.as_posix()
        finally:
            # Also runs on timeout, unexpected exceptions and cancellation.
            # Do not suppress the original exception while invalidating links.
            valid_source = _verify_source(audio)
        if not valid_source:
            break
