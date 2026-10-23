"""One bounded method/clip per process, including native RSS and decode costs."""
from dataclasses import asdict
import json
from pathlib import Path
import resource
import sys
import time

from audio_qc.models import Defect, DefectIssue
from .audio import PCMClip, detect_clip, score_events
from .runner import filtered, write_json


def key(variant):
    if variant['method'] == 'essentia': return f"essentia:{variant['detectionThreshold']:g}"
    if variant['method'] == 'baseline': return 'baseline'
    return f"{variant['method']}:{variant['window_ms']}:{variant['threshold']:g}"


def restore_issues(items):
    return [DefectIssue(**{**i, 'channel_events': [Defect(**e) for e in i['channel_events']]}) for i in items]


def execute(job):
    started = time.perf_counter()
    clip, family = job['clip'], job['family']
    result = {'variants': {}, 'error': None, 'clip': clip}
    try:
        with PCMClip(clip) as pcm:
            if family == 'baseline':
                issues, capped = detect_clip(pcm, clip)
                result['variants']['baseline'] = dict(events=score_events(pcm, issues, methods=()),
                    issues=[asdict(i) for i in issues], capped=capped, channels=pcm.channels)
            elif family in ('temporal', 'prediction'):
                base = json.loads(Path(job['baseline_file']).read_text())
                if base['error']: raise ValueError('Baseline measurement failed')
                base = base['variants']['baseline']
                windows = sorted({v['window_ms'] for v in job['variants']})
                events = score_events(pcm, restore_issues(base['issues']), methods=(family,), windows=windows)
                for v in job['variants']:
                    result['variants'][key(v)] = dict(events=filtered(events, v), capped=base['capped'],
                                                     channels=pcm.channels)
            elif family == 'essentia':
                from .essentia_detector import detect, runtime
                result['essentia'] = runtime()
                for v in job['variants']:
                    raw = Path(job['output_file']).with_suffix(f".{int(v['detectionThreshold'])}.raw.jsonl")
                    with raw.open('x', encoding='utf-8') as handle:
                        def sink(event):
                            handle.write(json.dumps(event, allow_nan=False)+'\n')
                        measured = detect(pcm, clip, v, raw_sink=sink)
                    result['variants'][key(v)] = {**measured, 'raw_file': raw.name}
            else:
                raise ValueError('Unknown experimental method')
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    factor = 1 if sys.platform == 'darwin' else 1024
    result['resources'] = {'elapsed_seconds': time.perf_counter()-started,
                           'peak_rss_bytes': int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)*factor,
                           'child_peak_rss_bytes': int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)*factor,
                           'scope': 'Fresh method/clip process. RSS includes imports; elapsed measures execution '
                                    '(PCM decode and listed variants), wall also includes interpreter/import startup. '
                                    'Child peak is max FFmpeg/ffprobe RSS, not simultaneous total.'}
    write_json(job['output_file'], result)


if __name__ == '__main__':
    execute(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
