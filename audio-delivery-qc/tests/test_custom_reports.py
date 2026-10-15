from copy import deepcopy
import json

from audio_qc.config import resolve_config
from audio_qc.issues import consolidate_issues
from audio_qc.models import AudioFile, Defect
from audio_qc.reports import build_report, write_reports
from audio_qc.reports.specification import specification_rows
from audio_qc.rules import assess_file


def test_effective_custom_report_preserves_schema_timecode_issues_and_links(tmp_path):
    policy=resolve_config({'preset':'CUSTOM','sample_rate':{'required':48000},
                           'bit_depth':{'required':24}, 'loudness':{'target_lufs':-14,'tolerance':1},
                           'true_peak':{'maximum':-6},'bwf':{'required':True},
                           'channels':{'allowed':[2,6]},'clipping':{'fail':False}})
    events=[Defect(n/48000,n,ch,'POSSIBLE CLICK / TICK',3/48000,None,{'duration_samples':3},'test')
            for n,ch in [(2529767,1),(2529770,2)]]
    audio=AudioFile('/not/read.wav','fixture',sample_rate=48000,channels=2,bit_depth=24,
                    bwf={'present':True,'time_reference':172800000},
                    measurements={'integrated_lufs':-14,'true_peak_dbtp':-6},
                    defects=consolidate_issues(events,48000,2))
    before=deepcopy(audio)
    assessed=assess_file(audio,policy)
    assessed.defects[0].snippet='defect_snippets/a & 日本語.wav'
    write_reports(build_report('/not/read.wav',[assessed],[],policy,{},0),tmp_path)
    report=json.loads((tmp_path/'QC_REPORT.json').read_text())
    assert report['schema_version']==3 and report['configuration']==policy
    issue,=report['files'][0]['defects']
    assert issue['channels']==[1,2] and len(issue['channel_events'])==2
    assert issue['sample_index']==2529767 and issue['timestamp_seconds'].hex()==events[0].timestamp_seconds.hex()
    assert issue['timecode']=='01:00:52:17'
    html=(tmp_path/'QC_REPORT.html').read_text()
    for text in ('Especificación efectiva · CUSTOM','48000 Hz','Requerido: 24; preferido: ninguno',
                 '-14 LUFS ± 1 LU','Máximo: -6 dBTP','Requerido','2, 6','WARNING; criterio existente',
                 '<h3>Defect issues</h3>','channel_events','target="_blank" rel="noopener"'):
        assert text in html
    assert "default-src 'none'" in html and '<script' not in html
    assert 'defect_snippets/a%20%26%20%E6%97%A5%E6%9C%AC%E8%AA%9E.wav' in html
    assert audio==before


def test_summary_discloses_report_only_disabled_and_unrestricted_rules():
    policy=resolve_config({'preset':'CUSTOM'})
    summary=dict(specification_rows(policy))
    assert summary['Loudness integrado']=='Solo informe (sin objetivo)'
    assert summary['True Peak']=='Solo informe (sin máximo)'
    assert summary['Sample Rate']=='Sin requisito'
    assert summary['BWF / BEXT']=='Ignorado'
    assert summary['Canales físicos']=='Sin restricción'
    policy['loudness']['enabled']=False
    summary=dict(specification_rows(policy))
    assert summary['Loudness integrado']=='Desactivado'
    assert 'medición desactivada' in summary['True Peak']
