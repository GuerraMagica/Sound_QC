"""Local v2 comparison with independent detector candidates and source provenance."""
import csv
import json
from urllib.parse import quote

from .benchmark_metrics import measure, compare
from .benchmark_worker import key
from .report import text, csv_text


def render(output, report, clips):
    with (output/'report.html').open('x', encoding='utf-8') as html, \
            (output/'candidates.csv').open('x', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['clip','programme','split','method','source','physical_channel','sample_index',
                         'end_sample_exclusive','classification','annotation','evidence','provenance'])
        html.write('<!doctype html><html lang="es"><meta charset="utf-8"><title>Comparación de clicks</title>'
                   '<style>body{font:16px system-ui;max-width:1300px;margin:2em auto;padding:1em}'
                   'table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:.4em}'
                   'pre{white-space:pre-wrap;overflow-wrap:anywhere}code{font-family:monospace}</style>'
                   '<h1>Baseline, confirmadores y Essentia independiente</h1>'
                   '<p>Experimento local. No constituye un certificado Netflix ni una decisión QC de producción. '
                   '«Rechazable» expresa la anotación profesional; su base se conserva en el manifiesto.</p>')
        html.write(f"<h2>{text(report['decision']['decision'])}</h2>")
        for target, title in (('reject','Defectos anotados como motivo de rechazo'),
                              ('technical','Todos los clicks técnicos confirmados')):
            html.write(f'<h2>{title} · reserva real</h2><table><tr><th>Método</th><th>Aciertos</th>'
                       '<th>Falsas alarmas</th><th>Omitidos</th><th>Precision</th><th>Recall</th>'
                       '<th>Retención baseline</th><th>FP/h fuente</th><th>FP/h canal</th>'
                       '<th>Dudosos</th><th>Sin clasificar</th><th>Cobertura</th></tr>')
            base = report['metrics']['validation']['real']['baseline'][target]
            for method, measured in report['metrics']['validation']['real'].items():
                m = measured[target]
                values = [method, m['true_positives'], m['false_alarms'], m['false_negatives'],
                          m['precision'],m['recall'],compare(base,m)['retention'],
                          m.get('false_alarms_per_source_hour'),m.get('false_alarms_per_channel_hour'),
                          m['uncertain'],m['unclassified'],'COMPLETA' if m['complete'] else 'INCOMPLETA']
                html.write('<tr>'+''.join(f'<td>{text(v) if v is not None else "No evaluable"}</td>' for v in values)+'</tr>')
            html.write('</table>')
        html.write('<p>Eventos por canal físico; no se suman a issues de programa. Las dudas quedan fuera de '
                   'precision/recall confirmados. Un cap, error o candidato sin clasificar impide aceptar eficacia. '
                   'Los confirmadores dependen de la baseline y no pueden recuperar sus omisiones.</p>')
        for label, payload in (('Decisiones y limitaciones', {'decision':report['decision'],'limitations':report['limitations']}),
                               ('Resultados por programa y omisiones',report['per_programme']),
                               ('Tiempo y memoria por método',report['resources']),
                               ('Resultados sintéticos y reales separados',report['metrics'])):
            html.write(f'<details><summary>{label}</summary><pre>{text(json.dumps(payload,ensure_ascii=False,indent=2))}</pre></details>')
        for index, clip in enumerate(clips,1):
            html.write(f"<h2>{text(clip['programme'])} · {text(clip['id'])} · {text(clip['split'])}</h2>"
                       f"<p>{text(clip['file'])}</p>")
            for method in ('baseline','temporal','prediction','essentia'):
                filename=f'clip_{index:04d}_{method}.json'
                record=json.loads((output/filename).read_text())
                variant='baseline' if method=='baseline' else key(report['selected'][method])
                result=record['variants'].get(variant,{'events':[],'capped':False})
                measured=measure(result['events'],clip['annotations'],clip['sample_rate'],
                                 complete=clip['reviewed'] and not record['error'] and not result['capped'])
                html.write(f'<details><summary>{text(method)}: {len(result["events"])} eventos</summary>'
                           f'<p>Error: {text(record["error"])} · Truncado: {result["capped"]}</p>'
                           f'<a href="{quote(filename)}" target="_blank" rel="noopener">Provenance completa</a>'
                           '<table><tr><th>Canal físico</th><th>Muestra</th><th>Clasificación de rechazo</th>'
                           '<th>Anotación</th><th>Escucha</th></tr>')
                for row in measured['rows']:
                    family='essentia' if method=='essentia' else 'baseline'
                    link=report['evidence'][clip['id']].get(f"{family}:{row['issue_index']}")
                    end=row.get('end_sample',row['original']['cluster_last_sample']+1)
                    action=(f'<a href="{quote(link,safe="/")}" target="_blank" rel="noopener">Fuente original</a>' if link else 'No disponible')
                    writer.writerow([csv_text(v) for v in (clip['id'],clip['programme'],clip['split'],method,
                        clip['file'],row['channel'],row['sample_index'],end,row['classification'],
                        row['annotation'],link or '',filename)])
                    html.write(f'<tr><td>{row["channel"]}</td><td><code>{row["sample_index"]}</code></td>'
                               f'<td>{text(row["classification"])}</td><td>{text(row["annotation"])}</td><td>{action}</td></tr>')
                html.write('</table></details>')
        html.write('</html>')
