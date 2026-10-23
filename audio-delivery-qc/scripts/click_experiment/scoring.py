"""Deterministic research scores, not probabilities or production QC decisions."""
import numpy as np

WINDOWS_MS = (25, 50)
THRESHOLDS = (4., 8., 16., 32.)


def unavailable(reason):
    return {'score': None, 'reason': reason}


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def prediction_error(context, candidate, order):
    """Fit only observed context; recursively predict the excluded interval."""
    center = float(np.median(context))
    x = context - center
    amplitude = rms(x)
    if amplitude < 1e-9 or len(x) < 4 * order:
        return None
    x = x / amplitude
    windows = np.lib.stride_tricks.sliding_window_view(x, order + 1)
    features, target = windows[:, :-1], windows[:, -1]
    try:
        coefficients, _, rank, singular = np.linalg.lstsq(features, target, rcond=1e-8)
    except np.linalg.LinAlgError:
        return None
    # Low-rank tonal contexts are valid least-squares fits; zero rank is not.
    if rank == 0 or not np.all(np.isfinite(coefficients)): return None
    residual = rms(target - features @ coefficients) * amplitude
    history = list(x[-order:])
    predicted = []
    for _ in candidate:
        value = float(np.dot(history[-order:], coefficients))
        if not np.isfinite(value) or abs(value) > 100:
            return None
        history.append(value); predicted.append(value * amplitude + center)
    error = float(np.max(np.abs(candidate - predicted)))
    return error / max(residual, 1e-7)


def score_context(pre, candidate, post, rate, *, methods=('temporal', 'prediction')):
    if min(len(pre), len(post), len(candidate)) == 0 or min(len(pre), len(post)) < rate * .02:
        return {m: unavailable('insufficient_context') for m in methods}
    if len(candidate) > rate * .02:
        return {m: unavailable('cluster_longer_than_20ms') for m in methods}
    if not all(np.all(np.isfinite(a)) for a in (pre, candidate, post)):
        return {m: unavailable('nonfinite_context') for m in methods}
    center = float(np.median(np.r_[pre, post]))
    peak = float(np.max(np.abs(candidate - center)))
    before, after = rms(pre - center), rms(post - center)
    temporal = {'score': peak / max(before, after, 1e-7),
                'reason': 'impulse_relative_to_stronger_surrounding_envelope',
                'pre_rms': before, 'post_rms': after, 'impulse_peak': peak}
    if 'prediction' not in methods:
        return {'temporal': temporal} if 'temporal' in methods else {}
    order = max(4, min(64, round(24 * rate / 48000)))
    forward = prediction_error(pre, candidate, order)
    backward = prediction_error(post[::-1], candidate[::-1], order)
    prediction = (unavailable('unreliable_prediction') if forward is None or backward is None else
                  {'score': min(forward, backward), 'reason': 'two_sided_prediction_error',
                   'forward': forward, 'backward': backward, 'order': order})
    return {m: v for m, v in {'temporal': temporal, 'prediction': prediction}.items() if m in methods}


def retain(score, threshold):
    return score['score'] is None or score['score'] >= threshold
