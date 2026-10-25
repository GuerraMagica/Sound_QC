"""Strict virtual-programme eligibility and measurement; no delivery thresholds."""
from dataclasses import dataclass, field
from pathlib import Path

from .hashing import source_signature
from .models import MeasurementOutcome, MeasurementState as MS, OperationalDiagnostic
from .process import ToolError
from .programme import LAYOUTS


@dataclass(frozen=True)
class ProgrammeInput:
    group_id: str
    layout: str
    ordered_members: tuple[tuple[str, Path], ...]
    sample_rate: int
    sample_count: int
    alignment: str
    source_signatures: dict[str, tuple[int, int, int]]


@dataclass
class ProgrammeEligibility:
    eligible: bool
    reasons: list[str]
    warnings: list[str]
    input: ProgrammeInput | None = None


@dataclass
class ProgrammeMeasurement:
    state: str
    method: str = 'virtual_multichannel'
    measurements: dict = field(default_factory=dict)
    measurement_outcomes: dict = field(default_factory=dict)
    operational_diagnostics: list[OperationalDiagnostic] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)


def programme_eligibility(group, files, signatures):
    reasons, warnings = [], []
    if group['validation_status'] != 'VALID':
        reasons.extend(r['message'] for r in group['reasons'])
        reasons.append('M5 group is not structurally VALID')
    by_path = {a.path: a for a in files}
    roles = LAYOUTS.get(group['layout'], ())
    members = group['members']
    if not roles or sorted(m['channel'] for m in members) != sorted(roles):
        reasons.append('Missing, duplicate or unsupported logical roles')
    paths = [m['file'] for m in members]
    if len(set(str(Path(p).resolve()) for p in paths)) != len(paths):
        reasons.append('Duplicate physical sources')
    rates, counts, refs = set(), set(), []
    for p in paths:
        a = by_path.get(p)
        if a is None:
            reasons.append(f'No measured source: {p}')
            continue
        outcome = a.measurement_outcomes.get('samples')
        count = a.measurements.get('decoded_sample_frames')
        if not outcome or outcome.state != MS.SUCCESS or type(count) is not int or count <= 0:
            reasons.append(f'Complete decoded samples required: {p}')
        else:
            counts.add(count)
        if type(a.sample_rate) is not int or a.sample_rate <= 0:
            reasons.append(f'Invalid sample rate: {p}')
        else:
            rates.add(a.sample_rate)
        if a.channels != 1 or not a.codec or not a.codec.startswith('pcm_'):
            reasons.append(f'Mono PCM required: {p}')
        if a.measurements.get('nonfinite_samples', 0) or a.bwf.get('errors') or any(
                d.affects_analysis
                for d in a.operational_diagnostics):
            reasons.append(f'Unreliable source samples: {p}')
        ref = a.bwf.get('time_reference') if a.bwf.get('present') else None
        if a.bwf.get('present') and (type(ref) is not int or not 0 <= ref < 2**64):
            reasons.append(f'Invalid BWF TimeReference: {p}')
            ref = None
        refs.append(ref)
        if p not in signatures:
            reasons.append(f'Missing source signature: {p}')
    if len(rates) != 1 or len(counts) != 1:
        reasons.append('Identical positive sample rates and exact sample counts required')
    if len({r for r in refs if r is not None}) > 1:
        reasons.append('Contradictory BWF TimeReference values; no realignment permitted')
    if any(r is None for r in refs):
        if group['requested_alignment'] != 'common_file_start':
            reasons.append('Missing BWF requires explicit common_file_start for programme measurement')
        else:
            warnings.append('Operator asserted common file start; some BWF origins unavailable')
    if reasons:
        return ProgrammeEligibility(False, reasons, warnings)
    mapping = {m['channel']: Path(m['file']) for m in members}
    inputs = ProgrammeInput(group['id'], group['layout'], tuple((r, mapping[r]) for r in roles),
                            next(iter(rates)), next(iter(counts)), group['alignment_mode'],
                            {p: signatures[p] for p in paths})
    return ProgrammeEligibility(True, [], warnings, inputs)


def verify_programme_sources(inputs):
    for path, expected in inputs.source_signatures.items():
        try:
            actual = source_signature(path)
        except OSError as exc:
            raise ToolError(f'Source changed or unavailable: {path}: {exc}') from exc
        if actual != expected:
            raise ToolError(f'Source changed since physical inspection: {path}')


# The same backend and parser as physical-file measurement.
from .loudness import run_loudness

CHANNEL_MAP = {'stereo': ('FL', 'FR'), '5.1': ('FL', 'FR', 'FC', 'LFE', 'SL', 'SR')}
METRICS = ('integrated_lufs', 'true_peak_dbtp', 'lra_lu', 'max_momentary_lufs', 'max_short_term_lufs')


def virtual_input_args(inputs):
    roles = LAYOUTS[inputs.layout]
    mapping = dict(inputs.ordered_members)
    args = ['ffmpeg', '-hide_banner', '-nostdin', '-nostats', '-v', 'info', '-xerror']
    filters = []
    for i, role in enumerate(roles):
        args += ['-protocol_whitelist', 'file,pipe', '-guess_layout_max', '0', '-channel_layout', 'mono', '-i', str(mapping[role])]
        # Double precision preserves integer and floating PCM values, also for mixed bit depths.
        # FFmpeg 6 needs the validated mono layout during filter negotiation too.
        filters.append(f'[{i}:a:0]aformat=sample_fmts=dbl:channel_layouts=mono,asetnsamples=n=1024:p=0[m{i}]')
    labels = ''.join(f'[m{i}]' for i in range(len(roles)))
    assignments = '|'.join(f'{i}.0-{channel}' for i, channel in enumerate(CHANNEL_MAP[inputs.layout]))
    layout = 'stereo' if inputs.layout == 'stereo' else '5.1(side)'
    filters.append(f'{labels}join=inputs={len(roles)}:channel_layout={layout}:map={assignments}')
    return args, ';'.join(filters)


def measure_programme(inputs, requirements, progress=None, *, cancel=None):
    if not requirements.ebur128:
        return ProgrammeMeasurement('DISABLED')
    provenance = {'group_id': inputs.group_id, 'layout': inputs.layout,
                  'channel_map': [{'logical_channel': role, 'source_path': str(path), 'physical_channel': 1,
                                   'ffmpeg_channel': channel}
                                  for role, channel in zip(LAYOUTS[inputs.layout], CHANNEL_MAP[inputs.layout])
                                  for path in [dict(inputs.ordered_members)[role]]],
                  'sample_rate': inputs.sample_rate, 'sample_count': inputs.sample_count,
                  'alignment': inputs.alignment, 'source_signatures': inputs.source_signatures,
                  'backend': 'FFmpeg ebur128', 'dualmono': False}
    try:
        if cancel:
            cancel.raise_if_cancelled()
        verify_programme_sources(inputs)
        args, graph = virtual_input_args(inputs)
        graph += ',ashowinfo@qc_count,ebur128=metadata=1:peak=true:dualmono=false,ametadata=mode=print[out]'
        args += ['-filter_complex', graph, '-map', '[out]', '-vn', '-sn', '-dn', '-f', 'null', '-']
        result = run_loudness(args, inputs.sample_count / inputs.sample_rate, progress,
                              timeout=requirements.timeout_seconds, cancel=cancel,
                              expected_samples=inputs.sample_count)
        verify_programme_sources(inputs)
        outcomes = result.pop('measurement_outcomes', {})
        diagnostics = []
        for metric in METRICS:
            required = ((metric == 'integrated_lufs' and requirements.loudness) or
                        (metric == 'true_peak_dbtp' and requirements.true_peak))
            outcome = outcomes.setdefault(metric, MeasurementOutcome(MS.ERROR, 'Missing measurement outcome'))
            if outcome.state == MS.ERROR:
                result[metric] = None
                diagnostics.append(OperationalDiagnostic(metric, outcome.reason or 'Measurement failed', required, required))
        state = 'ERROR' if any(d.required for d in diagnostics) else 'SUCCESS'
        return ProgrammeMeasurement(state, measurements=result, measurement_outcomes=outcomes,
                                    operational_diagnostics=diagnostics, provenance=provenance)
    except (ToolError, OSError, ValueError) as exc:
        if cancel:
            cancel.raise_if_cancelled()
        return ProgrammeMeasurement('ERROR', measurements=dict.fromkeys(METRICS),
            measurement_outcomes={k: MeasurementOutcome(MS.ERROR, str(exc)) for k in METRICS},
            operational_diagnostics=[OperationalDiagnostic('programme_measurement', str(exc), True, True)],
            provenance=provenance)
