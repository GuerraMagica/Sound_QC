"""Opt-in v2 complete-detector benchmark, independent of production policy."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
from threading import Thread
import time

import numpy as np
from audio_qc.config import load_config
from audio_qc.models import AudioFile
from audio_qc.process import check_tools, environment
from audio_qc.snippets import export_snippets
from .audio import check_baseline, fingerprint
from .benchmark_metrics import measure, compare, decide, coverage, rates
from .benchmark_worker import key, restore_issues
from .manifest import load_manifest
from .runner import variants as confirmer_variants, write_json

FAMILIES = ('baseline', 'temporal', 'prediction', 'essentia')


def grid():
    return {'baseline': [{'method': 'baseline'}],
            **{m: [v for v in confirmer_variants() if v['method'] == m] for m in ('temporal', 'prediction')},
            'essentia': [{'method': 'essentia', 'detectionThreshold': t} for t in (20, 30, 40)]}


def run_worker(clip, family, variants, output, index, *, timeout=300):
    """Kill the isolated process group on deadline/cancel; bounded diagnostic tail."""
    filename = f'clip_{index:04d}_{family}.json'
    job = dict(clip=clip, family=family, variants=variants, output_file=str(output/filename),
               baseline_file=str(output/f'clip_{index:04d}_baseline.json'))
    request = output/f'job_{index:04d}_{family}.json'
    write_json(request, job)
    root = Path(__file__).resolve().parents[2]
    env = {**environment(), 'PYTHONPATH': os.pathsep.join(map(str, [root/'src', root/'scripts']))}
    started = time.perf_counter()
    tail = deque(maxlen=8)
    proc = subprocess.Popen([sys.executable, '-m', 'click_experiment.benchmark_worker', str(request)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            env=env, start_new_session=True)
    def drain():
        while line := proc.stderr.readline(2048): tail.append(line.decode('utf-8', errors='replace'))
    thread = Thread(target=drain, daemon=True); thread.start()
    try:
        code = proc.wait(timeout=timeout)
    except BaseException:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.wait()
        raise
    finally:
        thread.join(timeout=2)
        proc.stderr.close()
    if code or not (output/filename).exists():
        raise RuntimeError(f'{family} worker failed ({code}): {"".join(tail)[-4096:]}')
    record = json.loads((output/filename).read_text())
    record['resources']['wall_seconds'] = time.perf_counter()-started
    return filename, record


def empty():
    return {'hits': [], 'missed': [], 'true_positives': 0, 'false_alarms': 0,
            'duplicates': 0, 'uncertain': 0, 'unclassified': 0}


def aggregate(output, records, *, real_only=False, programme=None):
    metrics, blockers, covered = {}, {}, {}
    for filename in records:
        record = json.loads((output/filename).read_text())
        clip = record['clip']
        if real_only and clip['origin'] != 'real': continue
        if programme is not None and programme != clip['programme']: continue
        for name, result in record['variants'].items():
            complete = clip['reviewed'] and not record['error'] and not result['capped']
            measured = measure(result['events'], clip['annotations'], clip['sample_rate'], complete=complete)
            issues = blockers.setdefault(name, [])
            issues.extend(f"{clip['id']}: {b}" for b in measured['blockers'])
            if record['error']: issues.append(f"{clip['id']}: {record['error']}")
            if result['capped']: issues.append(f"{clip['id']}: truncated detection coverage")
            if not measured['blockers']: covered.setdefault(name, []).append(clip)
            for target in ('technical', 'reject'):
                total = metrics.setdefault(name, {}).setdefault(target, empty())
                for field in ('hits', 'missed'):
                    total[field].extend(json.dumps([clip['id'], i]) for i in measured[target][field])
                for field in ('true_positives', 'false_alarms', 'duplicates', 'uncertain', 'unclassified'):
                    total[field] += measured[target][field]
    for name, targets in metrics.items():
        hours = coverage(covered.get(name, []))
        for values in targets.values():
            rates(values, not blockers[name])
            values.update(hours)
            for unit in ('source', 'channel'):
                seconds = hours[f'{unit}_seconds']
                values[f'false_alarms_per_{unit}_hour'] = (values['false_alarms']*3600/seconds
                    if seconds and not blockers[name] else None)
        targets['blockers'] = blockers[name]
    return metrics


def select(dev, choices):
    selected, problems = {}, []
    base = dev.get('baseline', {}).get('reject', empty())
    for family in FAMILIES[1:]:
        eligible = []
        for v in choices[family]:
            result = dev.get(key(v))
            if result and not result['blockers'] and base['hits']:
                values = result['reject']
                if not compare(base, values)['lost_baseline_hits'] and not values['missed']:
                    eligible.append(v)
        if eligible:
            selected[family] = min(eligible, key=lambda v: (dev[key(v)]['reject']['false_alarms'],
                                                           choices[family].index(v)))
        else:
            # A fixed diagnostic fallback, never silently present it as calibrated.
            selected[family] = (dict(method='essentia', detectionThreshold=30) if family == 'essentia'
                                else dict(method=family, window_ms=25, threshold=4.0))
            problems.append(f'{family}: no eligible development configuration; fixed diagnostic fallback')
    return selected, problems


def validation_names(metrics, selected):
    return {family: metrics.get('baseline' if family == 'baseline' else key(selected[family]),
                               {'technical': rates(empty(), False), 'reject': rates(empty(), False),
                                'blockers': ['No evaluated clips']}) for family in FAMILIES}


def conclusions(measured, common_blockers, selection_problems, programmes):
    results = {}
    for family in FAMILIES[1:]:
        base, alternative = measured['baseline'], measured[family]
        problems = [p for p in selection_problems if p.startswith(family+':')]
        results[family] = decide(base['reject'], alternative['reject'],
            common_blockers+problems+base['blockers']+alternative['blockers'], programmes)
    return results


def code_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}


def export_evidence(output, clips, selected):
    links, errors = {}, []
    for index, clip in enumerate(clips, 1):
        baseline = json.loads((output/f'clip_{index:04d}_baseline.json').read_text())
        essentia = json.loads((output/f'clip_{index:04d}_essentia.json').read_text())
        audio = AudioFile(clip['file'], Path(clip['file']).name, sample_rate=clip['sample_rate'])
        references, unique = {}, {}
        for family, record, variant in (('baseline', baseline, 'baseline'),
                                         ('essentia', essentia, key(selected['essentia']))):
            measured = record['variants'].get(variant, {})
            audio.channels = measured.get('channels', audio.channels)
            for i, issue in enumerate(restore_issues(measured.get('issues', []))):
                window = (issue.cluster_first_sample, issue.cluster_last_sample)
                if window not in unique:
                    unique[window] = len(audio.defects)
                    audio.defects.append(issue)
                references[f'{family}:{i}'] = unique[window]
        export_snippets(audio, output, load_config(), index)
        links[clip['id']] = {name: audio.defects[i].snippet for name, i in references.items()}
        errors.extend(f"{clip['id']}: {d.message}" for d in audio.operational_diagnostics)
    return links, errors


def run(manifest, output):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    if os.name != 'posix': raise ValueError('Experimental native resource isolation currently requires macOS/Linux')
    clips = load_manifest(manifest, expected_schema=2)
    if output.exists(): raise FileExistsError('Use a new experiment output directory')
    repo = Path(__file__).resolve().parents[3]
    if any(c['origin'] == 'real' for c in clips) and output.is_relative_to(repo):
        raise ValueError('Real experiment results must stay outside Git')
    if any(output.is_relative_to(Path(c['file']).parent) for c in clips):
        raise ValueError('Output must be separate from source directories')
    baseline = check_baseline()
    from .essentia_detector import runtime
    essentia = runtime()
    versions = check_tools()
    before = {c['file']: fingerprint(c['file']) for c in clips}
    seen = {}
    for c in clips:
        digest = before[c['file']]['sha256']
        for previous in seen.get(digest, []):
            if previous['programme'] != c['programme']:
                raise ValueError('Identical sources leak across programmes')
            if (set(previous['channels']) & set(c['channels']) and c['start_sample'] < previous['end_sample']
                    and previous['start_sample'] < c['end_sample']):
                raise ValueError('Identical source intervals multiply observations')
        seen.setdefault(digest, []).append(c)
    output.mkdir()
    write_json(output/'manifest_snapshot.json', {'schema_version': 2, 'clips': clips})
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    experiment_hashes = code_hashes()
    started, choices = time.perf_counter(), grid()
    files = {'development': [], 'validation': []}
    resources = {'development': {}, 'validation': {}}
    common_blockers, selected = [], None
    try:
        for split in ('development', 'validation'):
            for index, clip in enumerate(clips, 1):
                if clip['split'] != split: continue
                for family in FAMILIES:
                    options = choices[family] if split == 'development' or family == 'baseline' else [selected[family]]
                    filename, record = run_worker(clip, family, options, output, index)
                    files[split].append(filename)
                    if record['error']: common_blockers.append(f"{clip['id']}/{family}: {record['error']}")
                    stats = resources[split].setdefault(family, dict(elapsed_seconds=0., wall_seconds=0.,
                        peak_rss_bytes=0, child_peak_rss_bytes=0, dependency='baseline' if family in ('temporal','prediction') else None,
                        scope=record['resources']['scope']))
                    for field in ('elapsed_seconds', 'wall_seconds'): stats[field] += record['resources'][field]
                    for field in ('peak_rss_bytes', 'child_peak_rss_bytes'):
                        stats[field] = max(stats[field], record['resources'][field])
            if split == 'development':
                dev_all = aggregate(output, files[split])
                dev_real = aggregate(output, files[split], real_only=True)
                selected, selection_problems = select(dev_real or dev_all, choices)
                common_blockers.extend((dev_real or dev_all).get('baseline', {}).get('blockers', []))
                if not dev_real: common_blockers.append('No real development corpus')
                frozen = {'protocol': 'rejected-clicks-v2', 'selected': selected, 'grid': choices,
                          'selection_problems': selection_problems, 'baseline': baseline, 'essentia': essentia,
                          'manifest_sha256': manifest_hash, 'development_metrics': dev_real or dev_all,
                          'experiment_files': experiment_hashes,
                          'matching_tolerance_ms': 1, 'selection': 'development only; zero rejected-click misses/losses',
                          'acceptance': 'zero rejected-click misses/losses and >=50% false-alarm reduction; '
                                        '>=20 baseline rejection hits, >=20 false alarms, >=2 real validation programmes'}
                write_json(output/'frozen_selection.json', frozen)
                frozen_hash = hashlib.sha256((output/'frozen_selection.json').read_bytes()).hexdigest()
        val = {scope: validation_names(aggregate(output, files['validation'], real_only=scope=='real'), selected)
               for scope in ('all', 'real')}
        by_programme = {}
        for programme in sorted({c['programme'] for c in clips}):
            split = next(c['split'] for c in clips if c['programme'] == programme)
            by_programme[programme] = dict(split=split, metrics=validation_names(
                aggregate(output, files[split], programme=programme), selected))
        evidence, errors = export_evidence(output, clips, selected)
        common_blockers.extend(errors)
        after = {source: fingerprint(source) for source in before}
        intact = before == after
        if not intact: common_blockers.append('Source integrity changed')
        if hashlib.sha256((output/'frozen_selection.json').read_bytes()).hexdigest() != frozen_hash:
            common_blockers.append('Frozen selection changed')
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != manifest_hash:
            common_blockers.append('Corpus annotations changed during evaluation')
        if code_hashes() != experiment_hashes:
            common_blockers.append('Experimental code changed during evaluation')
        programmes = len({c['programme'] for c in clips if c['split']=='validation' and c['origin']=='real'})
        decisions = conclusions(val['real'], common_blockers, selection_problems, programmes)
        for stage in resources.values():
            for family, stats in stage.items():
                base = stage['baseline'] if stats['dependency'] else {}
                stats['pipeline_elapsed_seconds'] = stats['elapsed_seconds'] + base.get('elapsed_seconds',0)
                stats['pipeline_wall_seconds'] = stats['wall_seconds'] + base.get('wall_seconds',0)
                stats['pipeline_peak_rss_bytes'] = max(stats['peak_rss_bytes'], base.get('peak_rss_bytes',0))
        verdicts = {d['decision'] for d in decisions.values()}
        verdict = ('VIABLE' if 'VIABLE' in verdicts else 'INSUFFICIENT_EVIDENCE'
                   if 'INSUFFICIENT_EVIDENCE' in verdicts else 'NOT_VIABLE')
        report = dict(schema_version=2, experiment='independent-click-detector-v2', baseline=baseline,
            essentia=essentia, selected=selected, decision=dict(decision=verdict, methods=decisions),
            metrics={'development': {'all':dev_all,'real':dev_real},'validation':val},
            per_programme=by_programme, resources=resources, evidence=evidence, clip_files=files,
            source_integrity=intact, sources_before=before, sources_after=after,
            frozen_selection_sha256=frozen_hash, manifest_sha256=manifest_hash,
            experiment_files=experiment_hashes,
            runtime={'python':sys.version,'platform':platform.platform(),'numpy':np.__version__,**versions},
            elapsed_seconds=time.perf_counter()-started, blockers=common_blockers,
            limitations=['Not a Netflix certificate or production QC decision',
                         'Confirmed technical clicks and rejection-worthy events are separate targets',
                         'Unknown detections block complete precision/recall; uncertain events are separate',
                         'Counts are physical-channel events, not unique programme issues',
                         'A capped method or incomplete corpus cannot establish efficacy',
                         'Float32 analysis may round PCM32/float64 values; source audio is unchanged'])
        from .benchmark_report import render
        render(output, report, clips)
        write_json(output/'results.json', report)
        write_json(output/'EXPERIMENT_COMPLETE.json', {'decision':verdict})
        return report
    except (Exception, KeyboardInterrupt) as exc:
        try: write_json(output/'EXPERIMENT_ERROR.json', {'error':str(exc) or 'Cancelled','complete':False})
        except OSError: pass
        raise
