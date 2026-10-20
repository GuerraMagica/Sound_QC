"""One-to-one maximum matching; no unknown event is automatically a false alarm."""
from collections import deque


def classify(events, annotations, rate):
    tolerance = rate // 1000
    adjacency = []
    for e in events:
        nearby = [i for i, a in enumerate(annotations)
                  if e['channel'] == a['channel'] and
                  a['start_sample'] - tolerance <= e['sample_index'] <= a['end_sample'] - 1 + tolerance]
        # Opposite label classes within tolerance are unresolved, not interchangeable.
        # Filtering must never turn an intentional transient into a retained true click.
        if len({annotations[i]['kind'] for i in nearby}) > 1:
            nearby = []
        # Prefer nearest annotation, then stable ID. Matching may reassign to maximize cardinality.
        nearby.sort(key=lambda i: (abs(events[len(adjacency)]['sample_index'] - annotations[i]['start_sample']),
                                  annotations[i]['id']))
        adjacency.append(nearby)
    matched = {}
    # Iterative augmenting paths avoid recursion limits on densely annotated clips.
    for root in range(len(events)):
        queue, parents, seen_labels = deque([root]), {root: None}, set()
        found = None
        while queue and found is None:
            ei = queue.popleft()
            for ai in adjacency[ei]:
                if ai in seen_labels: continue
                seen_labels.add(ai)
                if ai not in matched:
                    found = (ei, ai); break
                old = matched[ai]
                if old not in parents:
                    parents[old] = (ei, ai); queue.append(old)
        if found is not None:
            ei, ai = found
            while True:
                matched[ai] = ei
                if parents[ei] is None: break
                ei, ai = parents[ei]
    assigned = {ei: ai for ai, ei in matched.items()}
    rows = []
    for i, event in enumerate(events):
        ai = assigned.get(i)
        duplicate = ai is None and bool(adjacency[i])
        if duplicate: ai = adjacency[i][0]
        kind = annotations[ai]['kind'] if ai is not None else None
        classification = ('unclassified' if kind is None else 'uncertain' if kind == 'uncertain'
                          else 'true_positive' if kind == 'technical_click' and not duplicate else 'false_alarm')
        rows.append({**event, 'annotation': annotations[ai]['id'] if ai is not None else None,
                     'classification': classification, 'duplicate': duplicate})
    return rows


def summarize(rows, annotations):
    hits = sorted({r['annotation'] for r in rows if r['classification'] == 'true_positive'})
    truth = {a['id'] for a in annotations if a['kind'] == 'technical_click'}
    return {'hits': hits, 'missed': sorted(truth - set(hits)), 'true_positives': len(hits),
            'false_alarms': sum(r['classification'] == 'false_alarm' for r in rows),
            'unclassified': sum(r['classification'] == 'unclassified' for r in rows),
            'uncertain': sum(r['classification'] == 'uncertain' for r in rows),
            'duplicates': sum(r['duplicate'] for r in rows)}


def comparison(base, alternative):
    retained = len(set(base['hits']) & set(alternative['hits']))
    return {'retained_baseline_hits': retained,
            'retention': retained / len(base['hits']) if base['hits'] else None,
            'false_alarm_reduction': 1 - alternative['false_alarms'] / base['false_alarms']
            if base['false_alarms'] else None,
            'lost_baseline_hits': sorted(set(base['hits']) - set(alternative['hits']))}


def choose(base, trials):
    eligible = [t for t in trials if 10 * len(set(base['hits']) & set(t['metrics']['hits'])) >= 9 * len(base['hits'])]
    if not base['hits'] or not base['false_alarms'] or not eligible: return None
    return min(eligible, key=lambda t: (t['metrics']['false_alarms'],
                                       0 if t['method'] == 'temporal' else 1,
                                       t['window_ms'], t['threshold']))


def acceptance(base, alternative, *, real_programmes, blockers):
    facts = comparison(base, alternative)
    reasons = list(blockers)
    if len(base['hits']) < 20: reasons.append('Fewer than 20 real baseline-detected technical clicks')
    if base['false_alarms'] < 20: reasons.append('Fewer than 20 real baseline false alarms')
    if real_programmes < 2: reasons.append('Fewer than two independent real validation programmes')
    decision = ('INSUFFICIENT_EVIDENCE' if reasons else
                'VIABLE' if 10 * facts['retained_baseline_hits'] >= 9 * len(base['hits'])
                and 2 * alternative['false_alarms'] <= base['false_alarms'] else 'NOT_VIABLE')
    return {'decision': decision, 'reasons': reasons, **facts}
