"""Detector and confirmer metrics under an explicit rejection-label protocol."""
from fractions import Fraction
from .metrics import classify, summarize, comparison


def rates(metrics, complete):
    tp, fp, fn = metrics['true_positives'], metrics['false_alarms'], len(metrics['missed'])
    metrics.update(false_negatives=fn,
                   precision=tp/(tp+fp) if complete and tp+fp else None,
                   recall=tp/(tp+fn) if complete and tp+fn else None,
                   complete=complete)
    return metrics


def measure(events, labels, rate, *, complete):
    blockers = [] if complete else ['Interval or analysis incomplete']
    if any('qc_disposition' not in a for a in labels): blockers.append('Missing rejection labels (schema 2 required)')
    technical_rows = classify(events, labels, rate)
    rejection_labels = [{**a, 'kind': {'reject': 'technical_click', 'acceptable': 'intentional_transient',
                                       'uncertain': 'uncertain'}.get(a.get('qc_disposition'), 'uncertain')}
                        for a in labels]
    rejection_rows = classify(events, rejection_labels, rate)
    technical = summarize(technical_rows, labels)
    reject = summarize(rejection_rows, rejection_labels)
    if technical['unclassified'] or reject['unclassified']: blockers.append('Unclassified detections')
    return {'technical': rates(technical, not blockers), 'reject': rates(reject, not blockers),
            'blockers': blockers, 'rows': rejection_rows}


def compare(base, alternative):
    return {**comparison(base, alternative),
            'additional_hits': sorted(set(alternative['hits']) - set(base['hits']))}


def decide(base, alternative, blockers, programmes, *, minimum_hits=20, minimum_false_alarms=20):
    reasons = list(blockers)
    if len(base['hits']) < minimum_hits: reasons.append('Insufficient real baseline rejection hits')
    if base['false_alarms'] < minimum_false_alarms: reasons.append('Insufficient real false alarms')
    if programmes < 2: reasons.append('Fewer than two independent real validation programmes')
    facts = compare(base, alternative)
    decision = ('INSUFFICIENT_EVIDENCE' if reasons else
                'VIABLE' if not facts['lost_baseline_hits'] and not alternative['missed']
                and alternative['false_alarms'] * 2 <= base['false_alarms'] else 'NOT_VIABLE')
    return dict(decision=decision, reasons=reasons, **facts)


def coverage(clips):
    sources, channels = {}, {}
    for c in clips:
        if not c['reviewed']: continue
        interval = (Fraction(c['start_sample'], c['sample_rate']), Fraction(c['end_sample'], c['sample_rate']))
        sources.setdefault(c['file'], []).append(interval)
        for ch in c['channels']: channels.setdefault((c['file'], ch), []).append(interval)
    def seconds(groups):
        total = Fraction(0)
        for intervals in groups.values():
            last = None
            for start, end in sorted(intervals):
                total += max(0, end-max(start, last if last is not None else start))
                last = max(end, last if last is not None else end)
        return float(total)
    return {'source_seconds': seconds(sources), 'channel_seconds': seconds(channels)}
