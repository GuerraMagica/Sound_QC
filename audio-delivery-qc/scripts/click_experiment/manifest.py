"""Strict, bounded annotations with explicit programme-level holdout separation."""
from pathlib import Path

import yaml
from audio_qc.config import UniqueLoader

KINDS = {'technical_click', 'intentional_transient', 'uncertain'}


def fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError(f'Expected fields {sorted(required)}; optional {sorted(optional)}')


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError('IDs and programme names must be non-empty strings <= 200 characters')
    return value


def load_manifest(path, *, expected_schema=None):
    path = Path(path).resolve()
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Manifest exceeds 2 MiB')
    try:
        data = yaml.load(path.read_text(encoding='utf-8'), Loader=UniqueLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError(f'Invalid YAML: {exc}') from exc
    fields(data, {'schema_version', 'clips'})
    if type(data['schema_version']) is not int or data['schema_version'] not in (1, 2):
        raise ValueError('Unsupported manifest schema_version')
    if expected_schema is not None and data['schema_version'] != expected_schema:
        raise ValueError('Manifest schema/mode mismatch: schema 1 uses the legacy experiment; schema 2 requires --essentia')
    if not isinstance(data['clips'], list) or not 1 <= len(data['clips']) <= 200:
        raise ValueError('Provide 1–200 clips')
    clips, ids, programmes, sources = [], set(), {}, {}
    for original in data['clips']:
        fields(original, {'id', 'programme', 'split', 'origin', 'file', 'sample_rate',
                          'start_sample', 'end_sample', 'channels', 'reviewed', 'annotations'})
        c = dict(original)
        cid, programme = name(c['id']), name(c['programme'])
        if cid in ids: raise ValueError('Duplicate clip ID')
        ids.add(cid)
        if c['split'] not in ('development', 'validation') or c['origin'] not in ('real', 'synthetic'):
            raise ValueError('Invalid split/origin')
        if programme in programmes and programmes[programme] != (c['split'], c['origin']):
            raise ValueError('Programme leaks between splits or origins')
        programmes[programme] = c['split'], c['origin']
        if type(c['reviewed']) is not bool: raise ValueError('reviewed must be boolean')
        rate = integer(c['sample_rate'], 'sample_rate', 1)
        if not 8000 <= rate <= 192000: raise ValueError('Supported rates: 8–192 kHz')
        start, end = integer(c['start_sample'], 'start_sample'), integer(c['end_sample'], 'end_sample', 1)
        if not 0 < end - start <= 60 * rate: raise ValueError('Clip must span >0 and <=60 seconds')
        channels = c['channels']
        if not isinstance(channels, list) or not 1 <= len(channels) <= 6:
            raise ValueError('Select 1–6 physical channels')
        if any(type(ch) is not int or not 1 <= ch <= 6 for ch in channels) or len(set(channels)) != len(channels):
            raise ValueError('Invalid or repeated physical channel')
        if not isinstance(c['file'], str) or not c['file'] or '\x00' in c['file'] or '://' in c['file']:
            raise ValueError('file must be a local path')
        source = (path.parent / c['file']).resolve()
        c['file'] = str(source)
        for prev in sources.get(source, []):
            if prev['programme'] != programme: raise ValueError('One source cannot have different programme IDs')
            if set(prev['channels']) & set(channels) and start < prev['end_sample'] and end > prev['start_sample']:
                raise ValueError('Overlapping evaluation intervals would double-count evidence')
        sources.setdefault(source, []).append(c)
        if not isinstance(c['annotations'], list) or len(c['annotations']) > 2000:
            raise ValueError('At most 2000 annotations per clip')
        label_ids, labels = set(), []
        for item in c['annotations']:
            extra = {'qc_disposition', 'basis'} if data['schema_version'] == 2 else set()
            fields(item, {'id', 'channel', 'start_sample', 'end_sample', 'kind'} | extra)
            a = dict(item)
            aid = name(a['id'])
            if aid in label_ids: raise ValueError('Duplicate annotation ID')
            label_ids.add(aid)
            integer(a['channel'], 'annotation channel', 1)
            if a['channel'] not in channels or a['kind'] not in KINDS: raise ValueError('Invalid annotation channel/kind')
            if extra:
                if a['qc_disposition'] not in ('reject', 'acceptable', 'uncertain'):
                    raise ValueError('Invalid qc_disposition')
                if a['basis'] not in ('operator', 'documented_rejection'):
                    raise ValueError('Invalid assessment basis')
                if a['kind'] == 'intentional_transient' and a['qc_disposition'] == 'reject':
                    raise ValueError('An intentional transient cannot label a rejected click')
                if a['kind'] == 'uncertain' and a['qc_disposition'] != 'uncertain':
                    raise ValueError('Uncertain events require uncertain disposition')
            s, e = integer(a['start_sample'], 'annotation start'), integer(a['end_sample'], 'annotation end', 1)
            if not start <= s < e <= end: raise ValueError('Annotation outside clip')
            if any(b['channel'] == a['channel'] and s < b['end_sample'] and e > b['start_sample'] for b in labels):
                raise ValueError('Overlapping annotations on one channel are ambiguous')
            labels.append(a)
        c['annotations'] = labels
        clips.append(c)
    return clips
