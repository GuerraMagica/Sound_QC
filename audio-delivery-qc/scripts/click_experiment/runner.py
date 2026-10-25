"""Development-only selection, sealed before held-out analysis; local results only."""
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import tracemalloc

import numpy as np
from audio_qc.config import load_config
from audio_qc.models import AudioFile
from audio_qc.process import ToolError, check_tools
from audio_qc.snippets import export_snippets
from .audio import PCMClip, check_baseline, detect_clip, fingerprint, score_events
from .manifest import load_manifest
from .metrics import acceptance, choose, classify, comparison, summarize
from .scoring import WINDOWS_MS, THRESHOLDS, retain


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def variants():
    return [{'method': method, 'window_ms': window, 'threshold': threshold}
            for method in ('temporal', 'prediction') for window in WINDOWS_MS for threshold in THRESHOLDS]


def variant_id(variant):
    return f"{variant['method']}:{variant['window_ms']}:{variant['threshold']:g}"


def filtered(events, variant):
    if variant is None: return events
    return [e for e in events if retain(e['scores'][str(variant['window_ms'])][variant['method']], variant['threshold'])]


def empty_metrics():
    return {'hits': [], 'missed': [], 'true_positives': 0, 'false_alarms': 0,
            'duplicates': 0, 'uncertain': 0, 'unclassified': 0, 'reviewed_source_seconds': 0,
            'reviewed_channel_seconds': 0}


def add_metrics(total, measured, clip):
    for key in ('hits', 'missed'):
        total[key].extend(json.dumps([clip['id'], a], ensure_ascii=False) for a in measured[key])
    for key in ('true_positives', 'false_alarms', 'duplicates', 'uncertain', 'unclassified'):
        total[key] += measured[key]
    seconds = (clip['end_sample'] - clip['start_sample']) / clip['sample_rate']
    total['reviewed_source_seconds'] += seconds
    total['reviewed_channel_seconds'] += seconds * len(clip['channels'])


def finalize_metrics(m):
    m['false_alarms_per_reviewed_source_hour'] = (m['false_alarms'] * 3600 / m['reviewed_source_seconds']
                                                if m['reviewed_source_seconds'] else None)
    m['false_alarms_per_reviewed_channel_hour'] = (m['false_alarms'] * 3600 / m['reviewed_channel_seconds']
                                                 if m['reviewed_channel_seconds'] else None)
    return m


def analyze_clip(clip, output, index):
    started = time.perf_counter()
    record = {'clip': clip, 'events': [], 'issues': [], 'capped': False, 'error': None}
    try:
        with PCMClip(clip) as pcm:
            record['source_signature'] = pcm.source_signature
            issues, capped = detect_clip(pcm, clip)
            record.update(events=score_events(pcm, issues), issues=[asdict(i) for i in issues],
                          capped=capped, channels=pcm.channels)
    except (ValueError, ToolError, OSError) as exc:
        record['error'] = str(exc)
    record['elapsed_seconds'] = time.perf_counter() - started
    filename = f'clip_{index:04d}.json'
    write_json(output / filename, record)
    return filename


def evaluate_records(output, files, candidates):
    totals = {'all': {}, 'real': {}}
    programmes, blockers, real_programmes = {}, [], set()
    for filename in files:
        record = json.loads((output / filename).read_text(encoding='utf-8'))
        clip = record['clip']
        if record['error']: blockers.append(f"{clip['id']}: analysis error: {record['error']}")
        if record['capped']: blockers.append(f"{clip['id']}: truncated by original shared 1000-issue cap")
        if not clip['reviewed']: blockers.append(f"{clip['id']}: interval not fully reviewed")
        for name, variant in candidates.items():
            rows = classify(filtered(record['events'], variant), clip['annotations'], clip['sample_rate'])
            measured = summarize(rows, clip['annotations'])
            if name == 'baseline' and measured['unclassified']:
                blockers.append(f"{clip['id']}: {measured['unclassified']} unclassified candidates")
            if (name == 'baseline' and clip['origin'] == 'real' and
                    (measured['true_positives'] or measured['false_alarms'])):
                real_programmes.add(clip['programme'])
            add_metrics(totals['all'].setdefault(name, empty_metrics()), measured, clip)
            if clip['origin'] == 'real':
                add_metrics(totals['real'].setdefault(name, empty_metrics()), measured, clip)
            add_metrics(programmes.setdefault(clip['programme'], {}).setdefault(name, empty_metrics()), measured, clip)
    for scope in totals.values():
        for name in candidates: finalize_metrics(scope.setdefault(name, empty_metrics()))
    for scope in programmes.values():
        for m in scope.values(): finalize_metrics(m)
    return totals, programmes, blockers, real_programmes


def evidence_for_discarded(record, selected, output, index):
    if selected is None or record['error']: return {}, []
    retained = {e['id'] for e in filtered(record['events'], selected)}
    indices = sorted({e['issue_index'] for e in record['events'] if e['id'] not in retained})
    if not indices: return {}, []
    # Reuse the established source snippet exporter, one original multichannel window per issue.
    from audio_qc.models import Defect, DefectIssue
    audio = AudioFile(record['clip']['file'], Path(record['clip']['file']).name,
                      sample_rate=record['clip']['sample_rate'], channels=record['channels'])
    audio.metadata['source_signature'] = record.get('source_signature')
    for i in indices:
        item = dict(record['issues'][i])
        item['channel_events'] = [Defect(**e) for e in item['channel_events']]
        audio.defects.append(DefectIssue(**item))
    export_snippets(audio, output, load_config(), index)
    return ({i: issue.snippet for i, issue in zip(indices, audio.defects)},
            [d.message for d in audio.operational_diagnostics])


def run(manifest, output):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    clips = load_manifest(manifest, expected_schema=1)
    if output.exists(): raise FileExistsError(f'Use a new output directory: {output}')
    repo = Path(__file__).resolve().parents[3]
    if any(c['origin'] == 'real' for c in clips) and output.is_relative_to(repo):
        raise ValueError('Real audio experiments must write outside the repository')
    if any(output.is_relative_to(Path(c['file']).parent) for c in clips):
        raise ValueError('Output must be separate from source directories')
    baseline = check_baseline()
    sources = {c['file']: fingerprint(c['file']) for c in clips}
    hashes = {}
    for c in clips:
        digest = sources[c['file']]['sha256']
        for previous in hashes.get(digest, []):
            if previous['programme'] != c['programme']:
                raise ValueError('Identical sources assigned to different programmes would leak evidence')
            if (set(previous['channels']) & set(c['channels']) and
                    c['start_sample'] < previous['end_sample'] and
                    c['end_sample'] > previous['start_sample']):
                raise ValueError('Identical source intervals would multiply observations')
        hashes.setdefault(digest, []).append(c)
    versions = check_tools()
    output.mkdir()
    write_json(output / 'manifest_snapshot.json', {'schema_version': 1, 'clips': clips})
    started = time.perf_counter()
    own_tracing = not tracemalloc.is_tracing()
    if own_tracing: tracemalloc.start()
    try:
        files = {'development': [], 'validation': []}
        for i, c in enumerate(clips, 1):
            if c['split'] == 'development': files['development'].append(analyze_clip(c, output, i))
        grid = variants()
        dev, dev_programmes, blockers, dev_real = evaluate_records(
            output, files['development'], {'baseline': None, **{variant_id(v): v for v in grid}})
        trials = [{**v, 'metrics': dev['all'][variant_id(v)]} for v in grid]
        selected = choose(dev['all']['baseline'], trials)
        if selected is not None: selected = {k: selected[k] for k in ('method', 'window_ms', 'threshold')}
        frozen = {'selected': selected, 'trials': trials, 'baseline': baseline,
                  'development_clips': [c['id'] for c in clips if c['split'] == 'development'],
                  'selection_uses': 'development only; minimum 90% paired baseline retention',
                  'parameters': {'windows_ms': WINDOWS_MS, 'thresholds': THRESHOLDS,
                                 'prediction_order': 'round(24 * sample_rate / 48000), bounded 4–64',
                                 'max_cluster_ms': 20, 'rcond': 1e-8},
                  'alternatives': {m: choose(dev['all']['baseline'], [t for t in trials if t['method'] == m])
                                   for m in ('temporal', 'prediction')}}
        # This file is sealed BEFORE any held-out decoding or scoring. Never updated or resumed.
        write_json(output / 'frozen_selection.json', frozen)
        frozen_hash = hashlib.sha256((output / 'frozen_selection.json').read_bytes()).hexdigest()
        for i, c in enumerate(clips, 1):
            if c['split'] == 'validation': files['validation'].append(analyze_clip(c, output, i))
        candidates = {'baseline': None, 'selected': selected}
        for m, trial in frozen['alternatives'].items():
            if trial is not None: candidates[m] = {k: trial[k] for k in ('method', 'window_ms', 'threshold')}
        validation, programmes, validation_blockers, real_programmes = evaluate_records(output, files['validation'], candidates)
        blockers += validation_blockers
        if selected is None: blockers.append('Development data cannot select a valid alternative')
        if not dev_real: blockers.append('No labelled real development programme')
        # Export ALL discarded candidates, including synthetic and development cases, grouped by original issue.
        evidence = {}
        for i, c in enumerate(clips, 1):
            filename = f'clip_{i:04d}.json'
            record = json.loads((output / filename).read_text(encoding='utf-8'))
            links, errors = evidence_for_discarded(record, selected, output, i)
            evidence[c['id']] = links
            blockers.extend(f"{c['id']}: evidence export: {e}" for e in errors)
        after, integrity_errors = {}, []
        for source in sources:
            try: after[source] = fingerprint(source)
            except (OSError, ValueError) as exc: integrity_errors.append(str(exc))
        intact = sources == after and not integrity_errors
        if not intact: blockers.append('Source integrity changed or could not be verified')
        if hashlib.sha256((output / 'frozen_selection.json').read_bytes()).hexdigest() != frozen_hash:
            blockers.append('Frozen selection changed during validation')
        report = {'schema_version': 1, 'experiment': 'click-confirmation-v1', 'baseline': baseline,
                  'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
                  'experiment_files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in Path(__file__).parent.glob('*.py')},
                  'runtime': {'python': sys.version, 'platform': platform.platform(), 'numpy': np.__version__, **versions},
                  'selected': selected, 'frozen_selection_sha256': frozen_hash,
                  'metrics': {'development': dev, 'validation': validation},
                  'per_programme': {'development': dev_programmes, 'validation': programmes},
                  'source_integrity': intact, 'sources_before': sources, 'sources_after': after,
                  'integrity_errors': integrity_errors, 'evidence': evidence,
                  'decision': acceptance(validation['real']['baseline'], validation['real']['selected'],
                                         real_programmes=len(real_programmes), blockers=blockers),
                  'elapsed_seconds': time.perf_counter() - started,
                  'peak_traced_bytes': tracemalloc.get_traced_memory()[1],
                  'memory_scope': 'Python/NumPy traced allocations only; excludes FFmpeg RSS and OS buffers',
                  'limitations': ['Candidate confirmation cannot recover baseline misses',
                                  'Counts are physical channel events, not unique programme defects',
                                  'No semantic recognition or guarantee of artistic intention',
                                  'Real data is local; no automatic production integration'],
                  'clip_files': files}
        from .report import render
        render(output, report, clips)
        write_json(output / 'results.json', report)
        # Marker only after every required report is delivered; never a QC PASS marker.
        write_json(output / 'EXPERIMENT_COMPLETE.json', {'decision': report['decision']['decision']})
        return report
    except (Exception, KeyboardInterrupt) as exc:
        try:
            write_json(output / 'EXPERIMENT_ERROR.json', {'error': str(exc) or 'Cancelled', 'complete': False})
        except OSError:
            pass
        raise
    finally:
        if own_tracing: tracemalloc.stop()
