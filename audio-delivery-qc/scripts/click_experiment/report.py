"""Local listening report: escaped text, original provenance, no JavaScript."""
import csv
from html import escape
import json
from urllib.parse import quote

from .metrics import classify, summarize
from .runner import filtered


def text(value):
    return escape(str(value), quote=True)


def csv_text(value):
    value = str(value)
    return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value


def render(output, report, clips):
    with (output / 'report.html').open('x', encoding='utf-8') as html, \
            (output / 'candidates.csv').open('x', encoding='utf-8', newline='') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['clip', 'programme', 'split', 'source', 'channel', 'sample_index',
                         'baseline_classification', 'annotation', 'retained', 'reason', 'evidence'])
        html.write('<!doctype html><html lang="es"><meta charset="utf-8"><title>Experimento de clicks</title>'
                   '<style>body{font:16px system-ui;max-width:1200px;margin:2em auto;padding:1em} '
                   'table{border-collapse:collapse;width:100%}td,th{border:1px solid #aaa;padding:.4em;text-align:left}'
                   'pre{white-space:pre-wrap;overflow-wrap:anywhere}code{font-family:monospace}</style>'
                   '<h1>Experimento de confirmación de clicks</h1><p>Evaluación local; no es un certificado QC.</p>')
        html.write(f"<h2>{text(report['decision']['decision'])}</h2><pre>{text(json.dumps(report['decision'], ensure_ascii=False, indent=2))}</pre>")
        html.write('<p>Se cuentan eventos por canal físico. Los issues consolidados son otra vista de los mismos '
                   'eventos, no se suman. Las tasas por hora de fuente pueden contar varias fuentes mono de un programa; '
                   'se incluye también la tasa por hora-canal. Las puntuaciones no son probabilidades.</p>')
        html.write(f"<h2>Comparación reservada</h2><pre>{text(json.dumps(report['metrics']['validation'], ensure_ascii=False, indent=2))}</pre>")
        html.write(f"<details><summary>Resultados por programa</summary><pre>{text(json.dumps(report['per_programme'], ensure_ascii=False, indent=2))}</pre></details>")
        html.write('<p>Los enlaces de evidencia conservan todos los canales de la fuente. Se exportan los issues '
                   'con al menos un candidato descartado por la alternativa seleccionada.</p>')
        for i, clip in enumerate(clips, 1):
            filename = f'clip_{i:04d}.json'
            record = json.loads((output / filename).read_text(encoding='utf-8'))
            rows = classify(record['events'], clip['annotations'], clip['sample_rate'])
            kept = {e['id'] for e in filtered(record['events'], report['selected'])}
            alt_rows = classify(filtered(record['events'], report['selected']), clip['annotations'], clip['sample_rate'])
            before = summarize(rows, clip['annotations']); after = summarize(alt_rows, clip['annotations'])
            html.write(f"<h2>{text(clip['programme'])} · {text(clip['id'])} · {text(clip['split'])}</h2>"
                       f"<p>{text(clip['file'])} · Issues originales: {len(record['issues'])}; "
                       f"candidatos de click por canal: {len(rows)} · Truncado: {record['capped']}</p>"
                       f"<p>Error: {text(record['error'])}; intervalo revisado: {clip['reviewed']}</p>"
                       f"<p>Clicks anotados omitidos por baseline: {text(before['missed'])}; "
                       f"por alternativa: {text(after['missed'])}</p>"
                       f'<a href="{quote(filename)}" target="_blank" rel="noopener">Provenance JSON completa</a>'
                       '<details><summary>Candidatos retenidos y descartados</summary><table><tr>'
                       '<th>Canal</th><th>Muestra exacta</th><th>Etiqueta</th><th>Decisión experimental</th><th>Motivo / escucha</th></tr>')
            for row in rows:
                variant = report['selected']
                score = (row['scores'][str(variant['window_ms'])][variant['method']] if variant else
                         {'score': None, 'reason': 'No alternative selected'})
                link = report['evidence'][clip['id']].get(row['issue_index'])
                action = (f'<a href="{quote(link, safe="/")}" target="_blank" rel="noopener">Escuchar fuente</a>' if link else '')
                reason = f"{score['reason']}; score={score['score']}"
                writer.writerow([csv_text(v) for v in (clip['id'], clip['programme'], clip['split'], clip['file'],
                                  row['channel'], row['sample_index'], row['classification'], row['annotation'],
                                  row['id'] in kept, reason, link or '')])
                html.write(f"<tr><td>{row['channel']}</td><td><code>{row['sample_index']}</code></td>"
                           f"<td>{text(row['classification'])} · {text(row['annotation'])}</td>"
                           f"<td>{'Retenido' if row['id'] in kept else 'Descartado'}</td>"
                           f"<td>{text(reason)} {action}</td></tr>")
            html.write('</table></details>')
        html.write('<p>Revisar los clicks reales descartados antes de proponer cualquier integración. '
                   'No reajustar parámetros con este conjunto reservado.</p></html>')
