"""Read-only programme preview worker. No Qt, decode, report or QC assessment."""
import json
from pathlib import Path
import stat
import sys

MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
# Non-BMP characters take 12 ASCII bytes as a JSON surrogate pair. Reserve room
# for the response envelope and the abbreviation/validation notices as well.
MAX_TEXT_CHARS = 16 * 1024


def error_response(request_id, message):
    return dict(request_id=request_id, status='ERROR', group_count=None, notice_count=0,
                truncated=False, text='Previsualización no disponible: ' + str(message)[:4000])


def encode_response(result):
    return (json.dumps(result, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def collect_preview(request):
    # Keep the Qt controller's import light; only the auxiliary process loads
    # discovery modules and performs filesystem operations.
    from .programme import discover_programmes
    from .scanner import discover

    request_id = request.get('request_id') if isinstance(request, dict) else None
    try:
        if (type(request_id) is not int or request_id < 0
                or set(request) != {'request_id', 'source', 'settings'}
                or not isinstance(request['source'], str)
                or not isinstance(request['settings'], dict)):
            raise ValueError('Invalid preview request')
        paths, notices = [], []
        if request['source']:
            source = Path(request['source']).expanduser()
            mode = source.stat().st_mode  # Missing/denied is not an empty programme list.
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError('Source must be a file or directory')
            paths, notices = discover(source)
        groups = discover_programmes(paths, request['settings'])

        def lines():
            if not groups:
                yield ('No se pudo confirmar la ausencia de grupos; revise los avisos de descubrimiento.' if notices else
                       'No naming groups found. Select source or load explicit YAML definitions.')
            for group in groups:
                yield (f'{group.name} ({group.layout}, {group.alignment}): ' +
                       ', '.join(f'{m.channel} ← {Path(m.file).name}' for m in group.members))
            if notices:
                yield 'Notices:'
                for notice in notices:
                    yield f'{notice.code}: {notice.message}'

        parts, remaining, truncated = [], MAX_TEXT_CHARS, False
        for line in lines():
            line += '\n'
            parts.append(line[:remaining])
            if len(line) > remaining:
                truncated = True
                break
            remaining -= len(line)
        text = ''.join(parts)
        if truncated:
            text += f'\nPrevisualización abreviada: {len(groups)} grupos, {len(notices)} avisos. Consulte el informe QC completo.\n'
        text += 'Media validation will run with QC.'
        return dict(request_id=request_id, status='PARTIAL' if notices else 'SUCCESS',
                    group_count=len(groups), notice_count=len(notices), truncated=truncated, text=text)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return error_response(request_id, exc)


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError('Preview request exceeds 4 MiB; QC remains available')
        result = collect_preview(json.loads(raw))
    except (ValueError, OSError) as exc:
        result = error_response(None, exc)
    sys.stdout.buffer.write(encode_response(result))
    return 2 if result['status'] == 'ERROR' else 0


if __name__ == '__main__':
    raise SystemExit(main())
